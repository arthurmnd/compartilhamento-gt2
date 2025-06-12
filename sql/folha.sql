SELECT
    cpf,
    nome_servidor,
    matricula,
    data_admissao,
    ente,
    esfera,
    orgao,
    lotacao,
    tipo_vinculo,
    vinculo,
    competencia,
    jornada,
    remuneracao
FROM
    [infocontas].[vw_TCEPE_Folha]
WHERE
    ANOFOLHA = $ano