import os
import logging
import logging.handlers
from datetime import datetime, date, timedelta, time
from jsonschema import validate, ValidationError

def configurar_log(config_email, nome_arquivo):
    """
    Configura os handlers necessários para o logging da execução e o envio de e-mail no caso de erros
    :param config_email: configuração da seção de e-mail
    """
    os.makedirs('./log/', exist_ok=True)

    handler_file = logging.handlers.TimedRotatingFileHandler('log/' + nome_arquivo + '.log', when="midnight", backupCount=60)

    if config_email and config_email.get('toaddrs'):
        toaddrs = config_email['toaddrs'].split(',')

        handler_email = logging.handlers.SMTPHandler(mailhost=(config_email['host'], config_email['port']),
                                                    fromaddr=config_email['fromaddr'],
                                                    toaddrs=toaddrs,
                                                    subject="Erro no {} do Alice".format(nome_arquivo),
                                                    credentials=(config_email['user'], config_email['pwd']))
        handler_email.setLevel(logging.ERROR)
        
        logging.basicConfig(handlers=[handler_file, handler_email],level=logging.INFO, format='%(levelname)s: %(asctime)s %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
        logging.info('Início de programa')
    else:
        logging.basicConfig(handlers=[handler_file],level=logging.INFO, format='%(levelname)s: %(asctime)s %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
        logging.info('Início de programa')
        logging.warning("Propriedade 'toaddrs' não configurada - email não será enviado")

def configurar_variaveis_ambiente(config_variaveis_ambiente):
    """
    Configura as varáveis de ambiente.
    :param config_variaveis_ambiente: configuração da seção de variáveis de ambiente
    """
    if config_variaveis_ambiente:
        for k, v in config_variaveis_ambiente.items():
            os.environ[k.upper()] = v
            logging.info("Configurando variável de ambiente: {} = {}".format(k.upper(), v))


def carregar_certificado(config_certificado):
    """
    Carrega as variáveis de ambiente apontando para um bundle de certificados
    :param config_certificado: configuração da seção de certificados
    """
    if config_certificado and 'arquivo' in config_certificado:
        os.environ['REQUESTS_CA_BUNDLE'] = config_certificado['arquivo']

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

def tratar_datas(args):
    data_hoje = converter_data(0)
    data_ontem = converter_data(1)
    
    #se não definir nenhum parâmetro, considera a data de hoje
    if not args.data and not args.data_inicio and not args.data_fim:
        args.data_inicio = data_hoje
        args.data_fim = data_hoje

    #se definir apenas data_fim, erro.
    if args.data_fim and not args.data_inicio:
        #logging.error("Ao definir uma data de fim, a data de início é obrigatória")
        raise Exception("Ao definir uma data de fim, a data de início é obrigatória") 

    #se definir apenas data_inicio, considera data_fim como a data de ontem.
    if args.data_inicio and not args.data_fim:
        args.data_fim = data_ontem

    #se definir o argumento data, considera apenas essa data
    if args.data:
        args.data_inicio = args.data
        args.data_fim = args.data

    return args


def converter_data(arg):
    """
    Converte argumentos de data para objetos do python. O argumento pode estar no formato DD/MM/AAAA ou
       ser fornecido com um inteiro representando o número de dias no passado (ex.: 0=hoje, 1=ontem, 10=10 dias atrás).
    :param arg: argumento a ser processado
    :return: objeto do tipo "date"
    """
    if str(arg).isnumeric():
        data = datetime.combine(date.today() - timedelta(days=int(arg)), time.min)
    else:
        data = datetime.strptime(arg, "%d/%m/%Y")
    return data

def formata_dataframe(map, df):
        df.rename(map, axis=1, inplace=True)
        #campos_map = list(map.values())
        lista = [x for x in list(map.values()) if x in df.columns]
        return df[lista]