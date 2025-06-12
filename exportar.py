# Importações da biblioteca padrão
import argparse
import csv
import json
import logging
import os
import sys
import traceback
import zipfile

# Importações de terceiros
import pandas as pd
import paramiko
import sqlalchemy as sa
from jsonschema import ValidationError, validate

# Importações locais
import util

_DESCRICAO=''
_EPILOGO = ''

class Exportador(object):
    def __init__(self, args):
        # Inicializando variáveis
        self.dir_destino = './out'
        self.exercicios = args.exercicios.split(',')
        self.apenas_upload = args.apenas_upload
        self.apenas_validar = args.apenas_validar

        # Carregar arquivo de configuração:
        with open(args.config, encoding='utf-8') as f:
            self.config = json.load(f)
        
        # Inicializando logging
        util.configurar_log(self.config['e-mail'], 'exportar.py')

        # Inicializar conexão ao banco
        self.engine = sa.create_engine(self.config['bd_url'])

        self.tc = self.config['tc_origem']

    
    def execute(self):
        try:
            arq_upload = []
            logging.info('Inicializando conexão com o banco de dados')
            con = self.engine.connect()            

            if self.apenas_upload:
                # Se for apenas upload, transfere todos os zips da pasta out para o SFTP, sem trazer novos dados do banco
                arq_upload = [x for x in os.listdir('out') if '.zip' in x]
            else:
                # Caso contrário, faz o download e preenche a lista de arquivos a serem enviados para o SFTP
                for e in self.exercicios:
                    for tipo in self.config['exportacao']['tipos_arquivo']:
                        logging.info(f'Processando arquivo do tipo "{tipo}" do exercício {e}')
                        item = self.config['exportacao'][tipo]

                        logging.info('Carregando consulta SQL')
                        with open(item['query'], 'r', encoding='utf-8') as f:
                            query = f.read().replace('$ano', e)
            
                        # Ajustando nome de arquivo para o TC/exercício correspondente
                        arquivo = item['arquivo'].replace('$ano', e).replace('$tc', self.tc.upper())

                        logging.info('Carregando JSON schema')
                        schema_path = item["layout"]
                        if not schema_path.endswith(".json") or not os.path.exists(schema_path):
                            logging.error("JSON schema de validação ausente")
                        else:
                            with open(schema_path, "r", encoding="utf-8") as f:
                                schema = json.load(f)

                        logging.info(f'Carregando dataframe a partir de consulta "{query}"')
                        query = sa.text(query)        
                        df = pd.read_sql_query(sql=query,con=con, chunksize=100000)
                                                                      
                        logging.info(f'Exportando dados em CSV para arquivo "{arquivo}.zip"')
                        arq = os.path.join(self.dir_destino, arquivo + '.csv')
                        incluir_header = item['header']

                        # Iteração sobre os chunks do dataframe (particionado para limitar uso de memória)
                        for chunk in df:
                            # Validando chunk de acordo com schema
                            validar_dataframe_schema(chunk, schema)
                            # Identifica apenas as colunas de tipo string (object ou string dtype)
                            string_cols = chunk.select_dtypes(include=["object", "string"]).columns
                            # Substitui delimitadores e quebras de linha apenas nessas colunas
                            chunk[string_cols] = chunk[string_cols].replace(
                                [item["delim"], r"[\r\n]+"], "", regex=True
                            )

                            chunk.to_csv(arq
                                        ,encoding='utf-8'
                                        ,index=False
                                        ,header=incluir_header
                                        ,sep=item['delim']
                                        ,mode='a'
                                        ,quoting=csv.QUOTE_NONE
                                        ,float_format="%.2f"
                                        ,lineterminator="\r\n")
                            incluir_header = False

                        logging.info(f'{arquivo}.zip exportado')
                        if not self.apenas_validar:
                            self.compactar(arq)
                            arq_upload.append(arquivo + '.zip')
            
            if not self.apenas_validar:
                print(arq_upload)
                self.enviar_arquivos(arq_upload)
            logging.info("Fim de programa")
        except Exception as e:
            logging.error('Erro ao executar rotina: {}'.format(str(e)))
            sys.exit()

    def compactar(self, arquivo):
        logging.info('Compactando arquivo')
        # Obtendo o caminho para o arquivo sem a extensão
        pref, _ = os.path.splitext(arquivo)
        # Criando zip com o mesmo nome e local do arquivo original
        arquivo_zip = zipfile.ZipFile(pref + '.zip', 'w', zipfile.ZIP_DEFLATED)
        arquivo_zip.write(arquivo, arcname=os.path.basename(arquivo))
        arquivo_zip.close()
        # Compactado, removendo arquivo original
        os.remove(arquivo)

    def enviar_arquivos(self, arquivos):
        logging.info('Estabelecendo conexão SFTP para envio dos arquivos')
        transport = paramiko.Transport((self.config['sftp']['host'], self.config['sftp']['port']))
        transport.connect(username=self.config['sftp']['user'], password=self.config['sftp']['pwd'])
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        logging.info(f'Conectado - realizando upload de {len(arquivos)} arquivos')
        for arq in arquivos:
            logging.info(f'Realizando o upload do arquivo "{arq}"')
            localpath = os.path.join(self.dir_destino, arq)
            remotepath = os.path.join(self.config['sftp']['dir'], arq)
            sftp.put(localpath, remotepath)
            # Removendo arquivo após envio
            os.remove(localpath)
        
        logging.info('Upload realizado - fechando conexão SFTP')
        sftp.close()

def validar_dataframe_schema(df, schema):
    """
    Valida um DataFrame contra um schema JSON.
    Lança erro com mensagem clara sobre a primeira regra violada.
    """
    records = [
    {k: v for k, v in row.items() if v is not None}
        for row in df.to_dict("records")
    ]
    try:
        validate(instance=records, schema=schema)
    except ValidationError as e:
        campo = list(e.path)[-1] if e.path else "(registro)"
        raise Exception(f"Erro de validação no campo '{campo}': {e.message}")


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
    parser.add_argument('--exercicios', type=str, required=True, 
                        help="Uma lista de anos separada por virgula (ex. '2020,2021,2022')")
    parser.add_argument('-u', '--apenas-upload', action='store_true', 
                        help='Faz apenas o upload de arquivos zip já gerados e armazenados na pasta out')
                        # Argumentos de linha de comando
    parser.add_argument("-v", "--apenas-validar", action="store_true", 
                        help="Apenas valida os dataframes e exporta os arquivos localmente")
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
    
    d = Exportador(args)
    d.execute()

def run():
    """
    Ponto de entrada para chamada via console.
    """
    try:
        main(sys.argv[1:])
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        sys.exit()

if __name__ == "__main__":
    run()