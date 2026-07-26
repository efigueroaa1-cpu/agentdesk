# -*- coding: utf-8 -*-
"""
core/tools/calc.py — Herramienta de calculo matematico seguro (AST, sin eval).

Extraido de core/tools.py (2026-07-26, Strangler Fig v1.3, incremento 3/N):
evaluacion de expresiones via AST (whitelist de funciones/operadores), sin
eval() ni acoplamiento. El dispatcher (core/tools.py) importa _calcular.
"""
import ast
import math


_CALC_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sum": sum, "len": len, "pow": pow,
    "sqrt": math.sqrt, "log": math.log,
    "floor": math.floor, "ceil": math.ceil,
}
_CALC_CONSTS = {"pi": math.pi, "e": math.e}
_CALC_BINOPS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


def _eval_matematica(nodo):
    """Evalúa recursivamente solo nodos aritméticos permitidos."""
    if isinstance(nodo, ast.Expression):
        return _eval_matematica(nodo.body)
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _CALC_BINOPS:
        return _CALC_BINOPS[type(nodo.op)](_eval_matematica(nodo.left), _eval_matematica(nodo.right))
    if isinstance(nodo, ast.UnaryOp) and isinstance(nodo.op, (ast.UAdd, ast.USub)):
        v = _eval_matematica(nodo.operand)
        return v if isinstance(nodo.op, ast.UAdd) else -v
    if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id in _CALC_FUNCS and not nodo.keywords):
        return _CALC_FUNCS[nodo.func.id](*[_eval_matematica(a) for a in nodo.args])
    if isinstance(nodo, ast.Name) and nodo.id in _CALC_CONSTS:
        return _CALC_CONSTS[nodo.id]
    if isinstance(nodo, (ast.List, ast.Tuple)):
        return [_eval_matematica(e) for e in nodo.elts]
    raise ValueError(f"operación no permitida: {type(nodo).__name__}")


async def _calcular(expresion: str, descripcion: str = "") -> str:
    """Evalúa una expresión matemática de forma segura (AST, sin eval)."""
    try:
        arbol     = ast.parse(expresion, mode="eval")
        resultado = _eval_matematica(arbol)
        resultado_fmt = f"{resultado:,.2f}" if isinstance(resultado, float) else f"{resultado:,}"
        ctx = f" ({descripcion})" if descripcion else ""
        return f"Resultado{ctx}: {resultado_fmt}\n(expresión: {expresion} = {resultado})"
    except ZeroDivisionError:
        return "Error: división por cero."
    except Exception as e:
        return f"Error en cálculo '{expresion}': {e}"
