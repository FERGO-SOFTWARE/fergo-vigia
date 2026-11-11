# fergo-vigia

Confere de fora, a cada 5 minutos, se cada sistema da FERGO responde, e avisa o aparelho do dono quando um cai, quando volta e quando o certificado está perto de vencer.

- Consulta só o endereço público `/ping` de cada sistema (`sistemas.json`). Nenhum dado de cliente passa por aqui.
- Fora do ar = duas passadas seguidas sem a resposta combinada. Enquanto continuar fora, lembra a cada 6 horas.
- Certificado: avisa faltando 7, 3 e 1 dia.
- O estado entre uma passada e outra fica em `estado.json`, na branch `estado`.
- O agendador do GitHub não é pontual: o aviso pode levar de 5 a 20 minutos.

## Segredo

`VIGIA_PUSH_TOKENS`: o código do aparelho, copiado no app FERGO em Ajustes › Notificações › "Copiar código do vigia". Mais de um aparelho: separar por vírgula.

Sem o segredo o vigia confere, mas não avisa ninguém.

## Sistema novo

Acrescentar uma linha em `sistemas.json` com `id` (o mesmo do app), `nome` e `ping`.
