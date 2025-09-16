# Bibliotecas da biblioteca padrão
import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

# Bibliotecas de terceiros
import pandas as pd
import pyodbc
import paramiko
import sqlalchemy as sa

# Módulos locais
import util

_DESCRICAO=''
_EPILOGO = ''

class Importador(object):
    def __init__(self, args):
        # Inicializando variáveis
        self.dir_temporario = './in'
        self.exercicios = args.exercicios.split(',') if args.exercicios != 'todos' else args.exercicios
        self.sobrescrever = args.sobrescrever
        
        print(self.exercicios)
        # Carregar arquivo de configuração:
        with open(args.config) as f:
            self.config = json.load(f)
        
        # Inicializando logging
        util.configurar_log(self.config['e-mail'], 'importar.py')

        # Inicializar conexão ao banco
        logging.info('Inicializando conexão ao banco e tabela de controle')
        self.engine = sa.create_engine(self.config['importacao']['bd_url'], fast_executemany=True)
        #self.engine = sa.create_engine(self.config['bd_url'])
        
        #self.df_controle = pd.read_sql_query(sa.text("SELECT * FROM infocontas.vw_ControleImportacao_UltimaImportacao"), con=self.engine)
        #print(self.df_controle)

        # Inicializar conexão SFTP
        logging.info('Inicializando conexão HTTP')
        self.transport = paramiko.Transport((self.config['sftp']['host'], self.config['sftp']['port']))
        self.transport.connect(username=self.config['sftp']['user'], password=self.config['sftp']['pwd'])
        self.sftp = paramiko.SFTPClient.from_transport(self.transport)

        self.data_importacao = datetime.now()
        
    
    def execute(self):
        try:            
            logging.info('Gerando lista de diretórios a serem importados')
            tcs = []
            if self.config['importacao']['tcs'] == "todos":
                tcs = [tc for tc in self.sftp.listdir(self.config['importacao']['dir_ftp']) if re.match(r'^tc.*', tc)]
            else:
                tcs = [tc for tc in self.sftp.listdir(self.config['importacao']['dir_ftp']) if tc in self.config['importacao']['tcs']]
            logging.info(f'Serão baixados os dado dos órgãos: {', '.join(tcs)}')
            
            # Carregando o dataframe com os registros da tabela de controle - arquivos já importados no banco de dados
            self.obter_controle()

            for tc in tcs:
                logging.info(f'Baixando dados do {tc}')
                # Gerar lista dos arquivos a serem importados:
                # Lista com o nome dos arquivos dos tipos que devem ser importados, substuindo o nome do TC
                lista_arquivos_tc = [(t, self.config['arquivos'][t]['arquivo'].replace('$tc', tc)) for t in self.config['importacao']['tipos_arquivo']]
                # Lista de exercícios, usando regex se forem passados "todos", dando match com qualquer exercício presente no ftp
                lista_exercicios = ['\\d{4}'] if self.exercicios == 'todos' else self.exercicios
                # Lista final de arquivos a serem buscados no FTP, combinando parâmetros de tc, ano e tipo de arquivo
                lista_arquivos_completos = [
                    (tipo, arquivo.replace('$ano', str(ano)) + '.zip')
                    for (tipo, arquivo) in lista_arquivos_tc
                    for ano in lista_exercicios
                ]
                # Conteúdo do diretório do TC no FTP
                conteudo_dir_ftp = self.sftp.listdir('/'.join([self.config['importacao']['dir_ftp'], tc]))
                # Lista final dos arquivos a serem importados, filtrando os que estão no diretório do TC:
                arquivos_zip = [
                    (tipo, arquivo) for arquivo in conteudo_dir_ftp
                    for (tipo, padrao) in lista_arquivos_completos
                    if re.fullmatch(padrao, arquivo, re.IGNORECASE)
                ]

                if arquivos_zip:
                    arquivos_str = '\n  - '.join(f"{arquivo}" for tipo, arquivo in arquivos_zip)
                    logging.info(f"Importando os arquivos:\n  - {arquivos_str}")
                else:
                    logging.info("Nenhum arquivo a importar.")

                for (tipo, arq) in arquivos_zip:
                    try:
                        logging.info(f'Início da importação de {arq}')
                        # Ajustando os paths para chamada
                        remotepath = '/'.join([self.config['importacao']['dir_ftp'], tc , arq])
                        localpath = Path(self.dir_temporario, arq)

                        # Chamada de função de download
                        novo_registro, localpath, id_ult_importacao = self.baixar_arquivo(tc, remotepath, localpath)

                        # Se é um novo arquivo ou se foi modificado, chama a função de carga
                        if novo_registro:
                            self.carregar_bd(tc, tipo, localpath, novo_registro, id_ult_importacao)
                    except Exception as e:
                        logging.warning(f'Erro ao importar {arq}: {str(e)}')
                        localpath.unlink()

            logging.info("Fim de programa")
        except Exception as e:
            logging.error('Erro ao executar importar.py: {}'.format(str(e)))
            sys.exit(1)


    def baixar_arquivo(self, tc, remotepath, localpath):
        # Só baixa se arquivo ainda não foi baixado, ou se data de modificação é mais recente que o registrado no banco
        #zip_path = Path(localpath)
        csv_file = localpath.stem + '.csv'

        logging.info('Verificando data de modificação do arquivo')
        registro = self.df_controle[(self.df_controle['arquivo_origem'] == csv_file)]
        #print(registro)
        #registro = pd.read_sql_query(sa.text(f"SELECT * FROM {self.config['importacao']['bd_schema']}.vw_ControleImportacao_UltimaImportacao WHERE arquivo_origem = :arq").bindparams(arq=csv_file), con=self.engine)
        data_modificacao = datetime.fromtimestamp(self.sftp.lstat(remotepath).st_mtime)
    
        if self.sobrescrever or registro.empty or data_modificacao > registro['data_modificacao'].iloc[0]:
            situacao_registro = (
                'Modo sobrescrever' if self.sobrescrever
                else 'Novo arquivo' if registro.empty
                else 'Arquivo modificado'
            )
            logging.info(f'{situacao_registro} - baixando {localpath.name}')
            self.sftp.get(remotepath=remotepath, localpath=localpath)
            logging.info('Arquivo baixado - descompactando')
            
            # Descompacta arquivo zip e depois o remove
            with zipfile.ZipFile(localpath, 'r') as zip_ref:
                filenames = zip_ref.namelist()
                # Encontra arquivo CSV correspondente no .zip, fazendo a busca case insensitive 
                match = [file for file in filenames if file.lower() == csv_file.lower()][0] if any(file.lower() == csv_file.lower() for file in filenames) else None
                if match is None:
                    raise(Exception(f'{csv_file} não encontrado no arquivo zip'))
                else:
                    zip_ref.extract(match, self.dir_temporario)
                    csv_file = match
            localpath.unlink()

            novo_registro = {"tc_origem":tc, "arquivo_origem":csv_file, "data_modificacao":data_modificacao, "data_importacao":self.data_importacao}

            return novo_registro, Path(self.dir_temporario, csv_file), None if registro.empty else registro['id'].iloc[0]
            
        elif data_modificacao <= registro['data_modificacao'].iloc[0]:
            logging.info('Arquivo não será baixado - atualizado no banco de dados')
            return None, None, None


    def carregar_bd(self, tc, tipo_arquivo, localpath, novo_registro, id_ult_importacao):
        arq = localpath.name
        logging.info(f'Iniciando carga de {arq} no banco de dados')
        print(f'Carga de {arq}')
        
        # Carregando arquivo de layout para obter colunas a serem inseridas
        schema_path = self.config['arquivos'][tipo_arquivo]['layout']
        if not schema_path.endswith(".json") or not os.path.exists(schema_path):
            logging.error("JSON schema de validação ausente")
        else:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)


        with self.engine.begin() as conn_registro:
            # Registro da carga vai fora da transação principal para registrar erro independentemente do rollback
            logging.info(f"Registrando carga atual - data de execução {str(novo_registro['data_importacao'])}")
            df_novo_registro = pd.DataFrame(novo_registro, index=[0])
            df_novo_registro.to_sql(name=self.config['importacao']['bd_tabela_controle'], con=conn_registro, schema=self.config['importacao']['bd_schema'], if_exists='append', index=False)

            # Obtém o id que acabou de ser inserido
            result = conn_registro.execute(sa.text(f"SELECT MAX(id) FROM {self.config['importacao']['bd_schema']}.{self.config['importacao']['bd_tabela_controle']} WHERE arquivo_origem = :arq").bindparams(arq=arq))
            id_importacao_atual = result.scalar()
            conn_registro.commit()
        
        try:
            with self.engine.begin() as conn_insercao:
                # Remove registros de cargas atneriores
                if id_ult_importacao is not None:
                    logging.info('Removendo registros de cargas anteriores')
                    del_ult_importacao = sa.text(f"DELETE FROM [{self.config['importacao']['bd_schema']}].{self.config['arquivos'][tipo_arquivo]['tabela_importacao']} WHERE [id_importacao] = :id_importacao")
                    del_ult_importacao = del_ult_importacao.bindparams(id_importacao=int(id_ult_importacao))
                    conn_insercao.execute(del_ult_importacao)            
                
                df = pd.read_csv(
                    localpath,
                    # compression='zip',
                    header=0 if self.config['arquivos'][tipo_arquivo]['header'] else None,
                    sep=self.config['arquivos'][tipo_arquivo]['delim'],
                    encoding='utf-8',
                    names=schema['items']['properties'].keys() if not self.config['arquivos'][tipo_arquivo]['header'] else None,
                    dtype='str',
                    quoting=csv.QUOTE_NONE,
                    chunksize=100000
                )
                n = 1
                for chunk in df:
                    print(f'Chunk {str(n)}')
                    # Valida cada chunk antes de inserir
                    #t1_val = time.time()
                    #util.validar_dataframe_schema(chunk, schema_validacao)
                    #t2_val = time.time()
                    #print(round(t2_val - t1_val, 2), 'segundos para validação do chunk')
                    chunk['tc_origem'] = tc
                    chunk['id_importacao'] = id_importacao_atual
                    
                    # Debug de right truncation:
                    #for col in chunk.select_dtypes(include=['object', 'string']):
                    #    max_len = chunk[col].astype(str).str.len().max()
                    #    print(f"Coluna: {col:30} | Tamanho máximo: {max_len}")
                    
                    chunk.to_sql(self.config['arquivos'][tipo_arquivo]['tabela_importacao'],schema=self.config['importacao']['bd_schema'],con=conn_insercao,index=False,if_exists='append')
                    n+=1

                query_update = sa.text(f"UPDATE {self.config['importacao']['bd_schema']}.{self.config['importacao']['bd_tabela_controle']} SET flag_importacao = :flag WHERE id = :id").bindparams(flag=1,id=id_importacao_atual)
                conn_insercao.execute(query_update)  
                conn_insercao.commit()
                logging.info('Arquivo importado com sucesso')

        except Exception as e:
            erro = e.args[0]
            print(erro)
            logging.warning(f'Erro na importação do arquivo {arq}: {erro}')
            self.registrar_erro(id_importacao_atual, erro)
        
        finally:
            localpath.unlink()
                
    
    def registrar_erro(self, id, descricao):
        with self.engine.begin() as conn:
            #query_update = sa.text(f"UPDATE {self.config['importacao']['bd_schema']}.ControleImportacao SET descricao_erro = '{descricao}' WHERE id = {id}")
            query_update = sa.text(f"UPDATE {self.config['importacao']['bd_schema']}.{self.config['importacao']['bd_tabela_controle']} SET descricao_erro = :descricao WHERE id = :id")
            query_update = query_update.bindparams(descricao=descricao, id=id)
            conn.execute(query_update)
            conn.commit()
    
    def obter_controle(self):
        logging.info('Obtendo do banco os arquivos já importados')
        # Obtendo dataframe da tabela de controle
        df_c = pd.read_sql_query(sa.text(f"SELECT * FROM {self.config['importacao']['bd_schema']}.{self.config['importacao']['bd_tabela_controle']}"), con=self.engine)
        # Filtra registro importados corretamente (flag_importacao = 1) e ordena pela data de importação (desc)
        df_c = df_c[df_c['flag_importacao'] == 1].sort_values(by='data_importacao', ascending=False)
        # Mantém apenas o registro referente à carga mais recente de cada arquivo
        self.df_controle = df_c.drop_duplicates(subset=['tc_origem', 'arquivo_origem'], keep='first')


def tratar_argumentos(args):
    """
    Efetua o processamento dos argumentos passados por linha de comando.
    :return: um objeto contendo todos os argumentos tratados
    """
    parser = argparse.ArgumentParser(description=_DESCRICAO,
                                     formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=_EPILOGO)
    parser.add_argument('--config', type=str, default='config.json',
                        help="Caminho para o arquivo de configuração no formato json (ex. 'config.json')")
    parser.add_argument('--exercicios', type=str, default="todos", 
                        help="Uma lista de anos separada por virgula (ex. '2020,2021,2022')")
    parser.add_argument("-s", "--sobrescrever", action="store_true", 
                        help="Sobrescreve os arquivos baixados no banco, mesmo que já tenham sido importados anteriormente")
    args = parser.parse_args(args)
    return args


def main(args):
    """
    Principal ponto de entrada. Permite chamadas externas.

    Args:
    args ([str]): Lista de parâmetros da linha de comando.
    """
    args = tratar_argumentos(args)
    print(args)
    
    d = Importador(args)
    d.execute()

def run():
    """
    Ponto de entrada para chamada via console.
    """
    try:
        main(sys.argv[1:])
    except Exception as e:
        #logging.error('Erro ao executar importar.py: {}'.format(str(e)))
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)

if __name__ == "__main__":
    run()