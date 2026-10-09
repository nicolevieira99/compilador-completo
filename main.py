from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import re
from lark import Lark, Transformer, UnexpectedInput
from lark.exceptions import VisitError

GRAMMAR = r"""
start: statement*
?statement: rule
rule: "QUANDO" expr "ENTAO" action_block ["SENAO" action_block] "FIM"
action_block: action+
action: NAME "(" [arguments] ")" ";"?
arguments: expr ("," expr)*
?expr: or_expr
?or_expr: and_expr ("OU" and_expr)*
?and_expr: not_expr ("E" not_expr)*
?not_expr: "NAO" not_expr -> neg
         | comparison
?comparison: sum (COMP sum)?
?sum: product (ADD product)*
?product: atom (MUL atom)*
?atom: NUMBER -> number
     | HORARIO -> horario
    | STRING -> text
    | "VERDADEIRO" -> true
    | "FALSO" -> false
     | NAME "(" [arguments] ")" -> call
     | NAME -> variable
     | "(" expr ")"
COMP.3: ">="|"<="|"=="|"!="|">"|"<"
ADD: "+"|"-"
MUL: "*"|"/"
HORARIO.3: /(?:[01][0-9]|2[0-3]):[0-5][0-9]/
NUMBER: /[0-9]+(?:\.[0-9]+)?/
STRING: /"[^"\n]*"/
NAME: /[A-Za-z_][A-Za-z0-9_]*/
%import common.WS
%ignore WS
"""

PARSER = Lark(GRAMMAR, parser="lalr", lexer="contextual", start="start")

@dataclass
class Node:
    kind: str
    value: Any = None
    children: list["Node"] | None = None
    type_hint: str | None = None

def n(kind, value=None, children=None, type_hint=None):
    return Node(kind, value, children or [], type_hint)

class BuildAST(Transformer):
    def start(self, xs): return n("program", children=list(xs))
    def rule(self, xs):
        return n("rule", children=[item for item in xs if isinstance(item, Node)])
    def action_block(self, xs): return n("block", children=list(xs))
    def action(self, xs):
        name = str(xs[0])
        args = xs[1].children if len(xs) > 1 and isinstance(xs[1], Node) else []
        return n("action", name, args)
    def arguments(self, xs): return n("args", children=list(xs))
    def number(self, xs):
        s = str(xs[0]); return n("number", float(s) if "." in s else int(s))
    def horario(self, xs):
        s = str(xs[0]); h, m = map(int, s.split(":"))
        return n("number", h * 60 + m, type_hint="horario")
    def text(self, xs): return n("text", str(xs[0])[1:-1])
    def true(self, xs): return n("boolean", True)
    def false(self, xs): return n("boolean", False)
    def variable(self, xs): return n("variable", str(xs[0]))
    def call(self, xs):
        name = str(xs[0]); args = xs[1].children if len(xs)>1 and isinstance(xs[1], Node) else []
        return n("call", name, args)
    def neg(self, xs): return n("not", children=[xs[0]])
    def COMP(self, token): return str(token)
    def ADD(self, token): return str(token)
    def MUL(self, token): return str(token)
    def comparison(self, xs):
        if len(xs)==1: return xs[0]
        return n("binary", str(xs[1]), [xs[0], xs[2]])
    def sum(self, xs): return self._fold(xs)
    def product(self, xs): return self._fold(xs)
    def or_expr(self, xs): return self._fold_named(xs, "OU")
    def and_expr(self, xs): return self._fold_named(xs, "E")
    def _fold(self, xs):
        out=xs[0]
        for i in range(1,len(xs),2): out=n("binary", str(xs[i]), [out,xs[i+1]])
        return out
    def _fold_named(self, xs, op):
        out=xs[0]
        for x in xs[1:]: out=n("binary", op, [out,x])
        return out

def parse(source: str) -> Node:
    for bad in re.findall(r'\b\d{1,2}:\d{2}\b', source):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', bad):
            raise LexicalError(f"Horário inválido '{bad}'. Use HH:MM entre 00:00 e 23:59.")
    try:
        tree = PARSER.parse(source)
        return BuildAST().transform(tree)
    except UnexpectedInput as e:
        raise SyntaxProjectError(f"Erro sintático próximo da linha {e.line}, coluna {e.column}.") from e
    except VisitError as e:
        raise SyntaxProjectError(str(e.orig_exc)) from e

class LexicalError(Exception): pass
class SyntaxProjectError(Exception): pass
class SemanticError(Exception): pass

SENSORS = {
    "temperatura": "numero",
    "umidade_solo": "numero",
    "umidade_ar": "numero",
    "luminosidade": "numero",
    "chuva": "booleano",
    "horario": "horario",
    "clima": "texto",
}
DEVICES = {
    "ventilador": "motor",
    "bomba": "bomba",
    "iluminacao": "luz",
    "valvula": "valvula",
    "alarme": "alarme",
    "janela_teto": "janela",
}
ACTIONS = {
    "ligar": {"params": ["dispositivo"], "devices": {"motor", "bomba", "luz", "alarme"}, "returns": "acao"},
    "desligar": {"params": ["dispositivo"], "devices": {"motor", "bomba", "luz", "alarme"}, "returns": "acao"},
    "abrir": {"params": ["dispositivo"], "devices": {"valvula", "janela"}, "returns": "acao"},
    "fechar": {"params": ["dispositivo"], "devices": {"valvula", "janela"}, "returns": "acao"},
    "irrigar": {"params": ["dispositivo", "numero"], "devices": {"bomba"}, "returns": "acao"},
    "avisar": {"params": ["texto"], "returns": "acao"},
}
SENSOR_RANGES = {
    "temperatura": (-10, 50),
    "umidade_solo": (0, 100),
    "umidade_ar": (0, 100),
    "luminosidade": (0, 100),
}
ACTION_RANGES = {"irrigar": (1, 60)}
WARNING_MESSAGES = []

def expr_key(node):
    return (
        node.kind,
        node.value,
        node.type_hint,
        tuple(expr_key(child) for child in node.children or []),
    )

def _expression_type(node):
    if node.kind == "number":
        return node.type_hint or "numero"
    if node.kind == "text":
        return "texto"
    if node.kind == "boolean":
        return "booleano"
    if node.kind == "variable":
        if node.value not in SENSORS:
            raise SemanticError(f"Sensor/variável desconhecido: '{node.value}'.")
        return SENSORS[node.value]
    elif node.kind == "call":
        if node.value in ACTIONS:
            raise SemanticError(f"A ação '{node.value}' não pode ser usada como expressão.")
        if node.value not in SENSORS:
            raise SemanticError(f"Sensor/função desconhecido: '{node.value}'.")
        if node.children:
            raise SemanticError(f"O sensor '{node.value}' não recebe parâmetros.")
        return SENSORS[node.value]
    if node.kind == "not":
        result_type = _expression_type(node.children[0])
        if result_type != "booleano":
            raise SemanticError(f"NAO só aceita uma condição lógica, recebeu {result_type}.")
        return "booleano"
    if node.kind == "binary":
        left_type = _expression_type(node.children[0])
        right_type = _expression_type(node.children[1])
        if node.value in ("+", "-", "*", "/"):
            if left_type != "numero" or right_type != "numero":
                raise SemanticError(
                    f"O operador '{node.value}' exige números, recebeu {left_type} e {right_type}."
                )
            if node.value == "/" and _constant_number(node.children[1]) == 0:
                raise SemanticError("Divisão por zero.")
            return "numero"
        if node.value in ("E", "OU"):
            if left_type != "booleano" or right_type != "booleano":
                raise SemanticError(
                    f"O operador '{node.value}' exige condições lógicas, recebeu {left_type} e {right_type}."
                )
            return "booleano"
        if left_type != right_type:
            raise SemanticError(
                f"Não é possível comparar {left_type} com {right_type} usando '{node.value}'."
            )
        if node.value not in ("==", "!=") and left_type not in ("numero", "horario"):
            raise SemanticError(
                f"O operador '{node.value}' só ordena números e horários, não {left_type}."
            )
        return "booleano"
    raise SemanticError(f"Expressão não suportada: {node.kind}.")

def validate_expr(node):
    return _expression_type(node)

def _constant_number(node):
    if node.kind == "number" and isinstance(node.value, (int, float)):
        return node.value
    if node.kind != "binary" or node.value not in ("+", "-", "*", "/"):
        return None
    left = _constant_number(node.children[0])
    right = _constant_number(node.children[1])
    if left is None or right is None or (node.value == "/" and right == 0):
        return None
    operations = {"+": lambda: left + right, "-": lambda: left - right,
                  "*": lambda: left * right, "/": lambda: left / right}
    return operations[node.value]()

def _sensor_range_warnings(node, warnings):
    if node.kind == "binary" and node.value in (">", "<", ">=", "<=", "==", "!="):
        left, right = node.children
        variable, constant = (left, right) if left.kind == "variable" else (right, left)
        value = _constant_number(constant)
        if variable.kind == "variable" and value is not None and variable.value in SENSOR_RANGES:
            minimum, maximum = SENSOR_RANGES[variable.value]
            if not minimum <= value <= maximum:
                warnings.append(
                    f"Aviso: '{variable.value}' vai de {minimum} a {maximum}; "
                    f"o valor {value} está fora da faixa."
                )
    for child in node.children or []:
        _sensor_range_warnings(child, warnings)

def validate_action(node):
    if node.value not in ACTIONS:
        raise SemanticError(f"Ação desconhecida: '{node.value}'.")
    spec=ACTIONS[node.value]
    args=node.children or []
    if len(args) != len(spec["params"]):
        raise SemanticError(f"A ação '{node.value}' espera {len(spec['params'])} argumento(s), recebeu {len(args)}.")
    for arg, expected in zip(args, spec["params"]):
        if expected == "dispositivo":
            if arg.kind != "variable" or arg.value not in DEVICES:
                raise SemanticError(f"Argumento de '{node.value}' deve ser um dispositivo válido.")
            allowed = spec.get("devices")
            if allowed and DEVICES[arg.value] not in allowed:
                raise SemanticError(
                    f"A ação '{node.value}' não aceita dispositivo do tipo '{DEVICES[arg.value]}'."
                )
        else:
            actual = validate_expr(arg)
            if actual != expected:
                raise SemanticError(
                    f"A ação '{node.value}' espera argumento {expected}, recebeu {actual}."
                )
            if expected == "numero" and node.value in ACTION_RANGES:
                value = _constant_number(arg)
                if value is not None:
                    minimum, maximum = ACTION_RANGES[node.value]
                    if not minimum <= value <= maximum:
                        raise SemanticError(
                            f"A ação '{node.value}' aceita valores de {minimum} a {maximum}; recebeu {value}."
                        )
    return (node.value, tuple(expr_key(a) for a in args))

def semantic_analysis(program: Node):
    warnings=[]
    conditions={}
    for rule_number, rule in enumerate(program.children, 1):
        if rule.kind != "rule" or len(rule.children)<2:
            raise SemanticError("Regra incompleta.")
        cond, then_block = rule.children[0], rule.children[1]
        if validate_expr(cond) != "booleano":
            raise SemanticError(f"A condição da regra {rule_number} deve ser lógica.")
        _sensor_range_warnings(cond, warnings)
        if len(rule.children)>2: else_block=rule.children[2]
        else: else_block=n("block")
        seen=set()
        for block in (then_block, else_block):
            for act in block.children:
                key=validate_action(act)
                if key in seen:
                    warnings.append(f"Aviso: ação repetida na mesma regra: {key[0]}{key[1]}.")
                seen.add(key)
        ck=expr_key(cond)
        if ck in conditions:
            warnings.append(f"Aviso: regra {conditions[ck]} e regra {rule_number} possuem condição idêntica.")
        else:
            conditions[ck]=rule_number
    return warnings

def clone(node):
    return Node(node.kind, node.value, [clone(child) for child in (node.children or [])], node.type_hint)

def _is_constant(node):
    return node.kind in ("number", "text", "boolean")

def _constant_operation(op, left, right):
    arithmetic = {
        "+": lambda: left + right,
        "-": lambda: left - right,
        "*": lambda: left * right,
        "/": lambda: left / right,
    }
    comparisons = {
        "==": lambda: left == right,
        "!=": lambda: left != right,
        ">": lambda: left > right,
        "<": lambda: left < right,
        ">=": lambda: left >= right,
        "<=": lambda: left <= right,
    }
    if op in arithmetic and not (op == "/" and right == 0):
        return arithmetic[op](), "numero"
    if op in comparisons:
        return comparisons[op](), "boolean"
    if op == "E":
        return bool(left and right), "boolean"
    if op == "OU":
        return bool(left or right), "boolean"
    return None

def optimize(node, report=None):
    """Otimize uma expressão e opcionalmente registre (técnica, antes, depois)."""
    optimized_children = [optimize(child, report) for child in (node.children or [])]
    current = Node(node.kind, node.value, optimized_children, node.type_hint)

    def record(technique, before, after):
        if report is not None:
            report.append((technique, show(before), show(after)))
        return after

    if current.kind == "not" and current.children[0].kind == "not":
        return record("Eliminação de dupla negação", current, current.children[0].children[0])

    if current.kind != "binary":
        return current

    operator, left, right = current.value, current.children[0], current.children[1]
    if _is_constant(left) and _is_constant(right):
        try:
            folded = _constant_operation(operator, left.value, right.value)
        except (TypeError, ValueError, ZeroDivisionError):
            folded = None
        if folded is not None:
            value, result_kind = folded
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            replacement = n(result_kind, value)
            return record("Constant folding", current, replacement)

    if operator == "+" and right.kind == "number" and right.value == 0:
        return record("Identidade aritmética", current, left)
    if operator == "+" and left.kind == "number" and left.value == 0:
        return record("Identidade aritmética", current, right)
    if operator == "-" and right.kind == "number" and right.value == 0:
        return record("Identidade aritmética", current, left)
    if operator == "*" and right.kind == "number" and right.value == 1:
        return record("Identidade aritmética", current, left)
    if operator == "*" and left.kind == "number" and left.value == 1:
        return record("Identidade aritmética", current, right)
    if operator == "*" and (
        (left.kind == "number" and left.value == 0)
        or (right.kind == "number" and right.value == 0)
    ):
        return record("Identidade aritmética", current, n("number", 0))
    if operator == "/" and right.kind == "number" and right.value == 1:
        return record("Identidade aritmética", current, left)
    if operator in ("E", "OU"):
        for constant, other in ((left, right), (right, left)):
            if constant.kind != "boolean":
                continue
            if operator == "E" and constant.value is True:
                return record("Simplificação lógica", current, other)
            if operator == "E" and constant.value is False:
                return record("Simplificação lógica", current, n("boolean", False))
            if operator == "OU" and constant.value is False:
                return record("Simplificação lógica", current, other)
            if operator == "OU" and constant.value is True:
                return record("Simplificação lógica", current, n("boolean", True))
    return current

class Otimizador:
    def __init__(self):
        self.relatorio = []

    def otimizar(self, program):
        self.relatorio = []
        optimized_rules = []
        for rule_number, rule in enumerate(program.children, 1):
            condition = optimize(rule.children[0], self.relatorio)
            if condition.kind == "boolean" and condition.value is False:
                self.relatorio.append(("Eliminação de código morto", f"Regra #{rule_number}", "removida"))
                continue
            blocks = []
            for block in rule.children[1:]:
                actions = [
                    n("action", action.value,
                      [optimize(argument, self.relatorio) for argument in action.children])
                    for action in block.children
                ]
                blocks.append(n("block", children=actions))
            optimized_rules.append(n("rule", children=[condition, *blocks]))
        return n("program", children=optimized_rules)

def show(node):
    if node.kind=="number": return str(node.value)
    if node.kind=="text": return f'"{node.value}"'
    if node.kind=="boolean": return "VERDADEIRO" if node.value else "FALSO"
    if node.kind=="variable": return node.value
    if node.kind=="not": return "NAO " + show(node.children[0])
    if node.kind=="binary": return f"({show(node.children[0])} {node.value} {show(node.children[1])})"
    if node.kind=="call": return f"{node.value}({', '.join(show(x) for x in node.children)})"
    if node.kind=="action": return f"{node.value}({', '.join(show(x) for x in node.children)})"
    return node.kind

def draw_ast(node):
    def label(current, context):
        if current.kind == "block":
            return f"{context} (bloco)" if context else "Bloco"
        if current.kind == "rule": return "Regra"
        if current.kind == "program": return "Programa"
        if current.kind == "action": return f"Ação {show(current)}"
        if current.kind == "binary": return f"Operador {current.value}"
        if current.kind == "not": return "NAO"
        return show(current)

    lines = []

    def visit(current, prefix="", last=True, root=True, context=""):
        connector = "" if root else ("└── " if last else "├── ")
        lines.append(prefix + connector + label(current, context))
        children = current.children or []
        for index, child in enumerate(children):
            child_context = ""
            if current.kind == "rule":
                child_context = ("CONDICAO", "ENTAO", "SENAO")[index]
            next_prefix = prefix + ("" if root else ("    " if last else "│   "))
            visit(child, next_prefix, index == len(children) - 1, False, child_context)

    visit(node)
    return "\n".join(lines)

def compile_expr(node, code):
    if node.kind=="number":
        code.append(("PUSH_CONST",node.value))
    elif node.kind=="text" or node.kind=="boolean":
        code.append(("PUSH_CONST",node.value))
    elif node.kind=="variable":
        code.append(("LOAD_SENSOR",node.value))
    elif node.kind=="not":
        compile_expr(node.children[0],code); code.append(("NOT",))
    elif node.kind=="binary":
        if node.value in ("E", "OU"):
            compile_expr(node.children[0], code)
            jump_op = "JUMP_IF_FALSE_OR_POP" if node.value == "E" else "JUMP_IF_TRUE_OR_POP"
            jump_index = len(code)
            code.append((jump_op, None))
            compile_expr(node.children[1], code)
            code[jump_index] = (jump_op, len(code))
            return
        compile_expr(node.children[0],code); compile_expr(node.children[1],code)
        opmap={"+":"ADD","-":"SUB","*":"MUL","/":"DIV",">":"GT","<":"LT",">=":"GE","<=":"LE","==":"EQ","!=":"NE","E":"AND","OU":"OR"}
        code.append((opmap[node.value],))
    elif node.kind=="call":
        code.append(("LOAD_SENSOR",node.value))
    else:
        raise ValueError(f"Expressão não suportada: {node.kind}")

def compile_actions(block):
    code=[]
    for act in block.children:
        args=[]
        params = ACTIONS[act.value]["params"]
        for expected, arg in zip(params, act.children):
            if expected == "dispositivo": args.append(arg.value)
            else:
                argcode=[]; compile_expr(arg,argcode); args.append(("EXPR",argcode))
        code.append(("ACTION",act.value,args))
    return code

def compile_program(program):
    compiled=[]
    for idx,rule in enumerate(program.children,1):
        cond, then_block=rule.children[0],rule.children[1]
        else_block=rule.children[2] if len(rule.children)>2 else n("block")
        cond_code=[]; compile_expr(cond,cond_code)
        compiled.append({"id":idx,"condition":cond_code,"entao":compile_actions(then_block),"senao":compile_actions(else_block)})
    return compiled

def eval_code(code, sensors):
    stack=[]
    pc=0
    while pc < len(code):
        ins=code[pc]
        pc += 1
        op=ins[0]
        if op=="PUSH_CONST": stack.append(ins[1])
        elif op=="LOAD_SENSOR": stack.append(sensors.get(ins[1],False))
        elif op=="NOT": stack.append(not stack.pop())
        elif op=="JUMP_IF_FALSE_OR_POP":
            if not stack[-1]: pc=ins[1]
            else: stack.pop()
        elif op=="JUMP_IF_TRUE_OR_POP":
            if stack[-1]: pc=ins[1]
            else: stack.pop()
        else:
            b=stack.pop(); a=stack.pop()
            funcs={"ADD":lambda:a+b,"SUB":lambda:a-b,"MUL":lambda:a*b,"DIV":lambda:a/b if b else 0,
                   "GT":lambda:a>b,"LT":lambda:a<b,"GE":lambda:a>=b,"LE":lambda:a<=b,"EQ":lambda:a==b,"NE":lambda:a!=b,
                   "AND":lambda:bool(a and b),"OR":lambda:bool(a or b)}
            stack.append(funcs[op]())
    return stack[-1] if stack else False

class Estufa:
    def __init__(self):
        self.sensores = {
            "temperatura": 20,
            "umidade_solo": 50,
            "umidade_ar": 50,
            "luminosidade": 50,
            "chuva": False,
            "horario": 0,
            "clima": "ensolarado",
        }
        self.dispositivos = {
            "ventilador": {"ligado": False},
            "bomba": {"ligado": False, "litros": 0},
            "iluminacao": {"ligado": False},
            "valvula": {"aberta": False},
            "alarme": {"ligado": False},
            "janela_teto": {"aberta": False},
        }
        self.log = []

    def executar_acao(self, name, args):
        if name in ("ligar", "desligar"):
            self.dispositivos[args[0]]["ligado"] = name == "ligar"
        elif name in ("abrir", "fechar"):
            self.dispositivos[args[0]]["aberta"] = name == "abrir"
        elif name == "irrigar":
            device, liters = args
            self.dispositivos[device]["ligado"] = True
            self.dispositivos[device]["litros"] = liters
        elif name == "avisar":
            self.log.append(f"AVISO: {args[0]}")
        self.log.append({"acao": name, "argumentos": list(args)})

class Runtime:
    def __init__(self, compiled, environment=None):
        self.compiled=compiled
        self.environment=environment or Estufa()
        self.last={r["id"]:False for r in compiled}
        self.log=[]
    def tick(self, sensors, label=None):
        self.environment.sensores.update(sensors)
        events=[]
        for rule in self.compiled:
            current=bool(eval_code(rule["condition"],self.environment.sensores))
            previous=self.last[rule["id"]]
            if current and not previous:
                block=rule["entao"]; edge="ENTAO"
            elif previous and not current:
                block=rule["senao"]; edge="SENAO"
            else:
                block=[]; edge=""
            for op,name,args in block:
                rendered=[]
                for arg in args:
                    if isinstance(arg,tuple) and arg[0]=="EXPR":
                        rendered.append(eval_code(arg[1],self.environment.sensores))
                    else: rendered.append(arg)
                self.environment.executar_acao(name, rendered)
                events.append({"evento":label or f"evento {len(self.log)+1}","regra":rule["id"],"borda":edge,"acao":name,"argumentos":", ".join(map(str,rendered))})
            self.last[rule["id"]]=current
        self.log.extend(events)
        return events

class CentralDeAutomacao(Runtime):
    def evento(self, sensor, value, label=None):
        return self.tick({sensor: value}, label)

def run_tests():
    tests=[]
    def add(name, fn, expected_exception=None):
        try:
            result=fn()
        except Exception as e:
            passed = expected_exception is not None and isinstance(e, expected_exception)
            tests.append((name, "PASSOU" if passed else "FALHOU", f"{type(e).__name__}: {e}"))
            return
        passed = expected_exception is None and bool(result)
        detail = str(result) if expected_exception is None else "nenhum erro foi gerado"
        tests.append((name, "PASSOU" if passed else "FALHOU", detail))

    valid_senao = 'QUANDO temperatura > 30 ENTAO ligar(ventilador) SENAO desligar(ventilador) FIM'
    add("válido: regra com SENAO", lambda: len(parse(valid_senao).children[0].children) == 3)
    add("válido: horário convertido", lambda: parse('QUANDO horario >= 18:30 ENTAO ligar(iluminacao) FIM').children[0].children[0].children[1].value == 1110)
    add("válido: ação com dois parâmetros", lambda: not semantic_analysis(parse('QUANDO temperatura > 20 ENTAO irrigar(bomba, 5) FIM')))
    add("válido: desenho da AST com SENAO", lambda: "ENTAO" in draw_ast(parse(valid_senao)) and "SENAO" in draw_ast(parse(valid_senao)))
    add("válido: sensor textual", lambda: not semantic_analysis(parse('QUANDO clima == "ensolarado" ENTAO abrir(janela_teto) FIM')))
    add("válido: expressão aritmética", lambda: not semantic_analysis(parse('QUANDO temperatura + 0 > 20 ENTAO ligar(ventilador) FIM')))
    add("erro léxico: hora 25:00", lambda: parse('QUANDO horario >= 25:00 ENTAO ligar(iluminacao) FIM'), LexicalError)
    add("erro léxico: hora 18:75", lambda: parse('QUANDO horario >= 18:75 ENTAO ligar(iluminacao) FIM'), LexicalError)
    add("erro sintático: sem FIM", lambda: parse('QUANDO temperatura > 30 ENTAO ligar(ventilador)'), SyntaxProjectError)
    add("erro sintático: ação sem fechar parêntese", lambda: parse('QUANDO temperatura > 30 ENTAO ligar(ventilador FIM'), SyntaxProjectError)
    add("erro sintático: SENAO vazio", lambda: parse('QUANDO temperatura > 30 ENTAO ligar(ventilador) SENAO FIM'), SyntaxProjectError)
    add("erro semântico: sensor inexistente", lambda: semantic_analysis(parse('QUANDO sensor_xyz > 30 ENTAO ligar(ventilador) FIM')), SemanticError)
    add("erro semântico: dispositivo inexistente", lambda: semantic_analysis(parse('QUANDO temperatura > 30 ENTAO ligar(drone) FIM')), SemanticError)
    add("erro semântico: tipo de dispositivo incompatível", lambda: semantic_analysis(parse('QUANDO temperatura > 30 ENTAO irrigar(ventilador, 5) FIM')), SemanticError)
    add("erro semântico: tipos incompatíveis", lambda: semantic_analysis(parse('QUANDO chuva > 5 ENTAO ligar(ventilador) FIM')), SemanticError)
    add("erro semântico: ação inválida no SENAO", lambda: semantic_analysis(parse('QUANDO chuva ENTAO ligar(ventilador) SENAO ligar(drone) FIM')), SemanticError)
    add("erro semântico: divisão por zero", lambda: semantic_analysis(parse('QUANDO temperatura / 0 > 5 ENTAO ligar(ventilador) FIM')), SemanticError)
    add("aviso semântico: ação repetida", lambda: any("repetida" in warning for warning in semantic_analysis(parse('QUANDO chuva ENTAO ligar(ventilador); ligar(ventilador) FIM'))))
    add("aviso semântico: condição repetida", lambda: any("idêntica" in warning for warning in semantic_analysis(parse('QUANDO chuva ENTAO ligar(ventilador) FIM QUANDO chuva ENTAO desligar(ventilador) FIM'))))
    add("runtime: bordas ENTAO e SENAO", lambda: _test_runtime_edges())
    add("otimizador: relatório de transformações", lambda: _test_optimizer_report())
    print("\n=== TESTES AUTOMÁTICOS ===")
    for name,status,detail in tests:
        print(f"{status:8} | {name} | {detail}")
    passed=sum(s=="PASSOU" for _,s,_ in tests)
    print(f"Resultado: {passed}/{len(tests)} testes passaram.")
    if passed != len(tests):
        raise SystemExit("Há testes falhando; revise as mensagens acima.")
    return tests

def _test_runtime_edges():
    program = parse('QUANDO temperatura > 30 ENTAO ligar(ventilador) SENAO desligar(ventilador) FIM')
    runtime = Runtime(compile_program(program))
    rising = runtime.tick({"temperatura": 31})
    steady = runtime.tick({"temperatura": 32})
    falling = runtime.tick({"temperatura": 20})
    return (
        any(event["borda"] == "ENTAO" for event in rising)
        and not steady
        and any(event["borda"] == "SENAO" for event in falling)
        and runtime.environment.dispositivos["ventilador"]["ligado"] is False
    )

def _test_optimizer_report():
    program = parse('QUANDO NAO NAO chuva E (temperatura * 1 > 20) ENTAO ligar(ventilador) FIM')
    optimizer = Otimizador()
    optimizer.otimizar(program)
    return (
        len(optimizer.relatorio) >= 2
        and all(len(item) == 3 and all(str(part) for part in item) for item in optimizer.relatorio)
    )

def demo():
    source = """
    QUANDO NAO NAO (temperatura + 0 > 30) ENTAO
        ligar(ventilador)
    SENAO
        desligar(ventilador)
    FIM

    QUANDO horario >= 18:30 ENTAO
        ligar(iluminacao)
    SENAO
        desligar(iluminacao)
    FIM
    """
    print("=== CASASCRIPT 2.0 | ESTUFA INTELIGENTE ===")
    ast=parse(source)
    warnings=semantic_analysis(ast)
    print("\nTabela de símbolos:")
    print("Sensores:", SENSORS)
    print("Dispositivos:", DEVICES)
    print("Ações:", ACTIONS)
    print("\nAvisos semânticos:", warnings or "Nenhum")
    print("\nAST:")
    print(draw_ast(ast))
    optimizer=Otimizador()
    opt_ast=optimizer.otimizar(ast)
    print("\nRelatório do otimizador (técnica | antes | depois):")
    for technique, before, after in optimizer.relatorio:
        print(f"{technique} | {before} | {after}")
    compiled=compile_program(opt_ast)
    print("\nAST otimizada:")
    print(draw_ast(opt_ast))
    print("\nBytecode (3 blocos por regra):")
    for r in compiled:
        print(f"Regra {r['id']} | CONDIÇÃO={r['condition']} | ENTAO={r['entao']} | SENAO={r['senao']}")
    runtime=Runtime(compiled)
    samples=[
      ("00:00",18,0),("04:00",19,0),("08:00",25,0),("10:00",32,0),
      ("11:00",34,0),("12:00",29,0),("13:00",27,0),("15:00",31,0),
      ("17:00",28,0),("18:30",24,1110),("20:00",22,1200),("23:59",20,1439)
    ]
    print("\n=== SIMULAÇÃO DE UM DIA (12 eventos de sensor) ===")
    print(f"{'Horário':8} | {'Temperatura':11} | {'ENTAO/SENAO disparados'}")
    print("-"*75)
    for clock,temp,minutes in samples:
        emitted=runtime.tick({"temperatura":temp,"horario":minutes,"umidade_solo":35,"umidade_ar":50,"luminosidade":40,"chuva":False},clock)
        labels=", ".join(f"R{e['regra']} {e['borda']}: {e['acao']}({e['argumentos']})" for e in emitted) or "—"
        print(f"{clock:8} | {temp:11} | {labels}")
    print("\n=== REGISTRO DE AÇÕES ===")
    if runtime.log:
        for e in runtime.log:
            print(f"{e['evento']:8} | Regra {e['regra']} | {e['borda']:5} | {e['acao']}({e['argumentos']})")
    else:
        print("Nenhuma ação foi disparada.")

if __name__ == "__main__":
    run_tests()
    demo()
