# CasaScript 2.0 — Compilador para Estufa Inteligente

Este projeto implementa um compilador e um runtime para uma pequena linguagem de automação de estufas. A aplicação permite descrever regras sobre temperatura, umidade, luminosidade, horário, chuva e clima, validá-las antes da execução e acionar dispositivos simulados. Em uma estufa real, regras inválidas ou incompatíveis podem deixar de irrigar, ventilar ou abrir uma janela quando necessário; por isso, o compilador verifica a estrutura, os tipos, os dispositivos e os limites antes de permitir a simulação.

## Arquivos

- [main.py](main.py): gramática, AST, análise semântica, otimizador, geração de bytecode, ambiente `Estufa`, runtime, testes e demonstração.
- [validar_requisitos.py](validar_requisitos.py): suíte externa de conformidade dos requisitos RF1–RF6.
- [introducao.md](introducao.md): enunciado e especificação completa do projeto.

## Como executar

O compilador usa Python e a biblioteca Lark. Instale a dependência e execute a bateria interna junto com a demonstração:

```powershell
python -m pip install lark
python main.py
```

Para validar os requisitos funcionalmente contra o módulo do compilador:

```powershell
python validar_requisitos.py main.py
```

A suíte externa termina com código de saída zero quando todas as verificações passam. A execução atualmente valida 20 verificações externas e 21 testes internos.

## Como o compilador funciona

O programa passa pelas seguintes fases:

1. **Análise léxica e sintática:** Lark constrói o parser LALR a partir de `GRAMMAR`. A gramática define regras `QUANDO ... ENTAO ... [SENAO ...] FIM`, expressões aritméticas e lógicas, chamadas de ação, textos, valores booleanos e horários. A função `parse` verifica previamente os horários inválidos e converte erros do parser em exceções do projeto.
2. **Construção da AST:** `BuildAST` converte a árvore do Lark em nós `Node`. Uma regra possui a condição, um bloco `ENTAO` e, se informado, um bloco `SENAO`. O horário vira um nó numérico em minutos e mantém a indicação de tipo `horario` para a análise semântica.
3. **Análise semântica:** `semantic_analysis` verifica sensores existentes, tipos compatíveis, retorno lógico das condições, ações conhecidas, quantidade e tipo de argumentos, compatibilidade entre ação e dispositivo e faixas numéricas. Ela devolve avisos para ações repetidas e condições duplicadas.
4. **Otimização:** `Otimizador` aplica constant folding, simplificações lógicas, eliminação de regras com condição falsa, eliminação de dupla negação e identidades aritméticas. Cada transformação é registrada como `(técnica, antes, depois)`.
5. **Geração de bytecode:** `compile_program` gera três blocos por regra: `condition`, `entao` e `senao`. As expressões usam instruções de pilha como `LOAD_SENSOR`, `PUSH_CONST`, comparadores, operações aritméticas e saltos de curto-circuito.
6. **Execução:** `Runtime.tick` atualiza os sensores do ambiente `Estufa`, avalia as condições e dispara ações apenas quando há mudança de estado: `ENTAO` na transição falso→verdadeiro e `SENAO` na transição verdadeiro→falso. `Estufa.executar_acao` altera o estado dos dispositivos e registra as ações.

A função `draw_ast` mostra a estrutura da AST, incluindo os blocos da regra. A função `demo` apresenta tabela de símbolos, avisos, AST original e otimizada, relatório do otimizador, bytecode e simulação tabular de 12 eventos.

## Tabela de símbolos da estufa

### Sensores

| Nome           | Tipo    | Faixa ou significado                                     |
| -------------- | ------- | -------------------------------------------------------- |
| `temperatura`  | número  | -10 a 50 °C                                              |
| `umidade_solo` | número  | 0 a 100%                                                 |
| `umidade_ar`   | número  | 0 a 100%                                                 |
| `luminosidade` | número  | 0 a 100%                                                 |
| `chuva`        | lógico  | verdadeiro ou falso                                      |
| `horario`      | horário | de 00:00 a 23:59; internamente, minutos desde meia-noite |
| `clima`        | texto   | descrição textual, por exemplo `"ensolarado"`            |

### Dispositivos

| Nome          | Tipo    |
| ------------- | ------- |
| `ventilador`  | motor   |
| `bomba`       | bomba   |
| `iluminacao`  | luz     |
| `valvula`     | válvula |
| `alarme`      | alarme  |
| `janela_teto` | janela  |

### Ações

| Ação       | Argumentos          | Dispositivos aceitos ou limite       |
| ---------- | ------------------- | ------------------------------------ |
| `ligar`    | dispositivo         | motor, bomba, luz ou alarme          |
| `desligar` | dispositivo         | motor, bomba, luz ou alarme          |
| `abrir`    | dispositivo         | válvula ou janela                    |
| `fechar`   | dispositivo         | válvula ou janela                    |
| `irrigar`  | dispositivo, número | bomba; volume de 1 a 60              |
| `avisar`   | texto               | mensagem registrada no log da estufa |

## Atendimento aos requisitos funcionais

### RF1 — Literal de horário

A gramática declara `HORARIO` com prioridade superior à de `NUMBER`, para que `18:30` seja um único token. `parse` rejeita formatos fora do intervalo válido com `LexicalError`; `BuildAST.horario` converte o valor para minutos desde a meia-noite. A geração de código emite esse número como `PUSH_CONST`. Por exemplo, `18:30` produz `1110`.

### RF2 — Bloco `SENAO`

A regra gramatical aceita um `SENAO` opcional. Cada bloco de ações exige pelo menos uma ação, então `SENAO FIM` é erro sintático. A AST, `draw_ast` e o bytecode distinguem os blocos `ENTAO` e `SENAO`. O runtime executa o segundo somente na borda de descida, isto é, quando a condição era verdadeira e passa a falsa.

### RF3 — Tabela de símbolos e análise semântica

A tabela possui sete sensores, cobrindo número, texto, lógico e horário, e seis dispositivos de tipos distintos. As ações incluem `irrigar(bomba, numero)` e `avisar(texto)`, além das ações de controle. `SENSOR_RANGES` e `ACTION_RANGES` declaram limites. `validate_action` rejeita argumentos inválidos, dispositivos incompatíveis e volumes fora da faixa. As ações dos dois blocos passam pelo mesmo validador. `semantic_analysis` também avisa quando uma mesma ação com os mesmos argumentos se repete na regra ou quando duas regras têm condições idênticas.

### RF4 — Otimizações

`optimize` faz as transformações nas expressões e registra o nome da técnica, o texto anterior e o resultado. As novas técnicas são:

- Dupla negação: `NAO NAO x` → `x`.
- Identidades aritméticas: `x + 0`, `x - 0`, `x * 1` e `x / 1` → `x`; `x * 0` → `0`.

O otimizador também preserva as otimizações de base: constant folding, simplificações lógicas e remoção de regras que sempre resultam em falso.

### RF5 — Bytecode e runtime

Cada regra compilada contém `condition`, `entao` e `senao`. O bytecode mantém a condição separada dos blocos de ação. `Runtime` usa uma instância de `Estufa` por padrão (ou um ambiente fornecido pelo chamador); a classe mantém sensores, estado dos dispositivos e log, e executa as ações suportadas. `CentralDeAutomacao.evento` oferece uma interface para atualizar um sensor por vez e avaliar as regras.

### RF6 — Testes e simulação

`run_tests` inclui casos válidos e erros léxicos, sintáticos e semânticos, verificando o tipo de exceção esperado, além de testes para `SENAO` vazio, erro em `SENAO`, avisos, otimizações e bordas do runtime. A demonstração executa uma sequência de 12 eventos e mostra disparos de `ENTAO` e `SENAO` em uma tabela. `validar_requisitos.py` complementa essa bateria com verificações independentes da estrutura e do comportamento do compilador.

## Exemplo de programa e bytecode

Programa CasaScript:

```text
QUANDO umidade_solo < 30 ENTAO
    irrigar(bomba, 10)
SENAO
    desligar(bomba)
FIM
```

A chamada `compile_program(parse(fonte))` produz a estrutura equivalente a:

```python
{
    "id": 1,
    "condition": [
        ("LOAD_SENSOR", "umidade_solo"),
        ("PUSH_CONST", 30),
        ("LT",),
    ],
    "entao": [
        ("ACTION", "irrigar", ["bomba", ("EXPR", [("PUSH_CONST", 10)])]),
    ],
    "senao": [
        ("ACTION", "desligar", ["bomba"]),
    ],
}
```

Quando a umidade do solo muda para menos de 30, o runtime irriga uma vez na borda de subida. Quando a condição deixa de ser verdadeira, executa `desligar(bomba)` na borda de descida. Se a condição permanecer no mesmo estado em eventos consecutivos, nenhuma ação é repetida.
