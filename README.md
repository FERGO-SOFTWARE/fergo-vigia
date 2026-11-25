# fergo-vigia

Confere de fora se cada sistema e site da FERGO responde e se o servidor está saudável, e avisa o aparelho do dono quando algo cai, quando volta e quando um certificado está perto de vencer.

- Consulta só endereços públicos (`sistemas.json`). Nenhum dado de cliente passa por aqui.
- Três tipos de conferência: `ping` (padrão: JSON com `ok: true`), `pagina` (basta responder 200) e `saude` (boletim que o servidor publica sobre si: certificados da origem, backups, disco e serviços; boletim com mais de 3 horas também conta como problema).
- Fora do ar = duas passadas seguidas sem a resposta combinada. Enquanto continuar fora, lembra a cada 6 horas.
- Certificado: avisa faltando 7, 3 e 1 dia.
- O estado entre uma passada e outra fica em `estado.json`, na branch `estado`.
- O agendador do GitHub não é pontual: o aviso pode levar de 5 a 20 minutos.

## Segredo

`VIGIA_PUSH_TOKENS`: o código do aparelho, copiado no app FERGO em Ajustes › Notificações › "Copiar código do vigia". Mais de um aparelho: separar por vírgula.

Sem o segredo o vigia confere, mas não avisa ninguém.

## Sistema novo

Acrescentar uma linha em `sistemas.json` com `id` (o mesmo do app), `nome`, `ping` (o endereço) e, se não for um `/ping`, o `tipo`.
