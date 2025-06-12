# 📤 Exportador de Dados (GT2)

Este sistema automatiza a **extração, validação, formatação e envio de dados** dos jurisdicionados dos Tribunais de Contas (TCs) para o FTP do Tribunal de Contas do Estado da Paraíba (TCE-PB), conforme regras padronizadas por layout.

## 🎯 Funcionalidade

O **exportador** realiza a entrega automatizada dos seguintes conjuntos de dados:

- **Empenhos**
- **Folhas de Pagamento**

Estes dados são processados e enviados a partir das bases dos **jurisdicionados de cada TC**, seguindo regras de validação definidas nos layouts oficiais pela coordenação do GT2 da Rede Infocontas. 

Ao utilizar o exportador, o usuário **não precisa** se preocupar com as regras de geração dos arquivos CSV, como codificação, separadores, etc. O código já realiza as atividades necessárias para exportar os arquivos em formato compatível definido no layout.

<aside>
  
[**📄Documento com layouts e regras para exportação**](https://docs.google.com/document/d/1KeNa2AEX4FLhHoAi5gsyOYB8b5ErzmzV/edit?pli=1)

</aside>

---

## ⚙️ Etapas do Script

A execução do script realiza as seguintes etapas:

1. **Extrair os dados do banco**
    
    Executa a consulta SQL associada ao tipo de dado (folha, empenhos), para cada ano de execução selecionado.
    
2. **Transformar em um DataFrame (Pandas)**
    
    Os dados extraídos são convertidos para um DataFrame para tratamento e validação.
    
3. **Validar contra o layout JSON Schema**
    
    O DataFrame é validado conforme as regras definidas em arquivos `layout_*.json`. Essas regras incluem:
    
    - Tipos de dados
    - Tamanhos mínimos e máximos de campos
    - Formatos de datas
    - Valores permitidos ou padrões esperados
4. **Gerar CSV e compactar**
    
    Caso os dados estejam válidos, o DataFrame é exportado para um arquivo `.csv`, delimitado conforme especificação, e compactado em `.zip`.
    
5. **Enviar ao FTP do TCE-PB**
    
    O arquivo `.zip` é transferido via SFTP ao servidor do TCE-PB.
    

## 🏁 Instruções para Início da Utilização

### 1. Criar as consultas SQL por tipo de dado

Cada TC deve preparar uma consulta SQL para cada um dos tipos de dados a serem enviados:

- `folha`
- `empenhos`

A consulta deve **usar o parâmetro `$ano`**, que será substituído automaticamente pelo exercício selecionado durante a execução do script. Os valores a serem atribuídos a esse parâmetro serão passados via linha de comando na execução do código.

---

### 2. Configurar ambiente Python

- Instalar o Python 3.9
- Instalar os pacotes com o pip:

```bash
pip install -r /path/to/requirements.txt
```

---

### 3. Configurar o arquivo de configuração `config.json`

Ajuste pelo menos os seguintes campos:

| **Campo** | **Descrição** |
| --- | --- |
| **tc_origem** | Identificador do TC, Exemplo: `"tce_am"` |
| **bd_url** | String de conexão com o banco. Exemplo: `"mssql+pyodbc://usuario:senha@host/banco?driver=ODBC+Driver+18+for+SQL+Server"` |
| **bd_schema** | Schema do banco onde estão as tabelas/views relevantes |
| **sftp/user** | Usuário no FTP do TCE-PB |
| **sftp/pwd** | Senha no FTP do TCE-PB |
| **exportacao/tipos_arquivo** | Lista com tipos de arquivos que o TC irá enviar ao TCE-PB. Exemplo:`["Empenhos", "Folha"]` |

Os demais campos podem permanecer como estão, a menos que o TC deseje alterar a estrutura de arquivos ou modificar o comportamento do exportador. 

<aside>
💡

Alguns campos do arquivo de configuração não estão sendo utilizados, pois se referem ao processo de importação, a outras funcionalidades ainda não implementadas ou ao modelo de dados de despesas, que foi descontinhado.

</aside>

---

### 4. Executar manualmente ou automatizar

### 🖥️ Exemplo de execução manual:

```bash
python exportar.py --config config.json --exercicios 2024,2025
```

### 🕒 Para agendamento automático:

Utilize o `cron` (Linux), `Agendador de Tarefas` (Windows) ou algum orquestrador como o Apache Airflow para rodar o script mensalmente, de acordo com a data estabelecida pela coordenação do GT2, passando os anos adequados como parâmetro na execução.

---

### 5. Verificar logs e corrigir erros

Os logs de execução gerados pelo script estão presentes na pasta `📁 log` e irão conter as informações referentes à execução da rotina. No caso de erros de validação, o log irá registrar o **primeiro erro identificado** na validação do schema, informando a coluna problemática e o erro em questão.

O usuário pode incluir a flag `-v` ou `--validar-apenas` no comando enquanto se certifica que seus arquivos estão de acordo com o padrão. Esta função faz com que o exportador realize apenas as etapas de extração, validação e exportação do arquivo csv para a pasta `📁 out` , sem realizar a compactação e o envio dos arquivos ao FTP.

---

## 📎 Conteúdo do arquivo

- `📁 layouts` –  Contém os arquivos JSON Schema utilizados para validação
- `📁 sql`  – Contém os arquivos com consultas SQL a serem executadas para extração dos dados do banco que serão exportados
- `📁 in` – Diretório utilizado para armazenamento temporário dos arquivos
- `📁 out` – Diretório utilizado para armazenamento temporário dos arquivos
- `📁 log` – Contém os logs em que poderão ser verificados eventuais erros de execução
- `exportador.py` – Script principal
- `util.py` – Arquivo com funções utilitárias para o script
- `config_exemplo.json` – Arquivo de configuração de exemplo a ser modificado pelo TC
- `requirements.txt` – Lista de dependências Python a serem instaladas

---
