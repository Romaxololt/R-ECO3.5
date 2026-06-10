"""
prism.py — Mathematical functions module for R-ECO3
Version : 1.1
"""

import math
import re as _re


# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def _parse_float(s: str, name: str = "value") -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid number for {name}: {s!r}")


def _fmt(x) -> str:
    """Format result: int if whole, complex if complex, else float."""
    if isinstance(x, complex):
        if x.imag == 0:
            return _fmt(x.real)
        r = f"{x.real:g}" if x.real != 0 else ""
        sign = "+" if x.imag >= 0 else ""
        i = f"{x.imag:g}i"
        return f"{r}{sign}{i}" if r else i
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "∞" if x > 0 else "-∞"
    if x == int(x):
        return str(int(x))
    return f"{x:g}"


# ══════════════════════════════════════════════════════════════════
#  EXPRESSION EVALUATOR  (no eval, no external deps)
# ══════════════════════════════════════════════════════════════════

_MATH_FUNCS = {
    'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
    'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
    'sinh': math.sinh, 'cosh': math.cosh, 'tanh': math.tanh,
    'asinh': math.asinh, 'acosh': math.acosh, 'atanh': math.atanh,
    'sqrt': math.sqrt, 'cbrt': lambda x: math.copysign(abs(x) ** (1/3), x),
    'log': math.log, 'log2': math.log2, 'log10': math.log10,
    'exp': math.exp, 'abs': abs,
    'ceil': math.ceil, 'floor': math.floor, 'round': round,
    'sign': lambda x: (1 if x > 0 else -1 if x < 0 else 0),
}
_MATH_CONSTS = {
    'pi': math.pi, 'e': math.e, 'tau': math.tau,
    'phi': (1 + math.sqrt(5)) / 2, 'inf': math.inf,
}
_PREC       = {'+': 1, '-': 1, '*': 2, '/': 2, '%': 2, '^': 3}
_RIGHT_ASSOC = {'^'}
_TOKEN_RE   = _re.compile(r'\d+\.?\d*|\.\d+|[+\-*/^%()]|[a-zA-Z_]\w*')


def _eval_expr(expr: str, x=None) -> float:
    """
    Evaluate a mathematical expression string.
    Supports: +  -  *  /  ^  %  unary-minus  parentheses
              functions: sin cos tan asin acos atan sinh cosh tanh
                         asinh acosh atanh sqrt cbrt log log2 log10
                         exp abs ceil floor round sign
              constants: pi e tau phi inf
              variable:  x
    """
    tokens = _TOKEN_RE.findall(expr.replace(' ', ''))
    output: list = []
    ops:    list = []

    def _apply(op):
        b = output.pop()
        a = output.pop()
        if   op == '+': output.append(a + b)
        elif op == '-': output.append(a - b)
        elif op == '*': output.append(a * b)
        elif op == '/':
            if b == 0: raise ZeroDivisionError("division by zero")
            output.append(a / b)
        elif op == '%':
            if b == 0: raise ZeroDivisionError("modulo by zero")
            output.append(a % b)
        elif op == '^': output.append(a ** b)

    prev = 'op'  # track previous token type for unary minus
    for tok in tokens:
        if _re.fullmatch(r'\d+\.?\d*|\.\d+', tok):
            output.append(float(tok))
            prev = 'num'
        elif tok == 'x':
            if x is None:
                raise ValueError("variable 'x' used but no value was provided")
            output.append(float(x))
            prev = 'num'
        elif tok in _MATH_CONSTS:
            output.append(_MATH_CONSTS[tok])
            prev = 'num'
        elif tok in _MATH_FUNCS:
            ops.append(tok)
            prev = 'func'
        elif tok == '(':
            ops.append('(')
            prev = 'op'
        elif tok == ')':
            while ops and ops[-1] != '(':
                _apply(ops.pop())
            if not ops:
                raise ValueError("Mismatched parentheses")
            ops.pop()
            if ops and ops[-1] in _MATH_FUNCS:
                fn = ops.pop()
                output.append(_MATH_FUNCS[fn](output.pop()))
            prev = 'num'
        elif tok in _PREC:
            if tok == '-' and prev in ('op', None):
                output.append(0.0)
            while (ops and ops[-1] in _PREC and
                   ((tok not in _RIGHT_ASSOC and _PREC[ops[-1]] >= _PREC[tok]) or
                    (tok in _RIGHT_ASSOC     and _PREC[ops[-1]] >  _PREC[tok]))):
                _apply(ops.pop())
            ops.append(tok)
            prev = 'op'
        else:
            raise ValueError(f"Unknown token in expression: {tok!r}")

    while ops:
        op = ops.pop()
        if op == '(':
            raise ValueError("Mismatched parentheses")
        _apply(op)

    if not output:
        raise ValueError("Empty expression")
    return output[0]


# ══════════════════════════════════════════════════════════════════
#  NUMERICAL CALCULUS
# ══════════════════════════════════════════════════════════════════

def _num_deriv(f, x: float, h: float = 1e-7) -> float:
    """Numerical derivative via central differences."""
    return (f(x + h) - f(x - h)) / (2 * h)


def _num_deriv2(f, x: float, h: float = 1e-5) -> float:
    """Numerical second derivative."""
    return (f(x + h) - 2 * f(x) + f(x - h)) / (h * h)


def _simpson(f, a: float, b: float, n: int = 1000) -> float:
    """Numerical integration via composite Simpson's rule."""
    if n % 2 == 1:
        n += 1
    h = (b - a) / n
    s = f(a) + f(b)
    for i in range(1, n):
        s += (4 if i % 2 == 1 else 2) * f(a + i * h)
    return s * h / 3


def _find_root_newton(f, x0: float, tol: float = 1e-9, max_iter: int = 500) -> float:
    """Newton-Raphson root finding."""
    x = x0
    for _ in range(max_iter):
        fx  = f(x)
        dfx = _num_deriv(f, x)
        if abs(dfx) < 1e-15:
            raise ValueError("Derivative too small — Newton-Raphson failed to converge")
        x_new = x - fx / dfx
        if abs(x_new - x) < tol:
            return x_new
        x = x_new
    raise ValueError(f"Newton-Raphson did not converge after {max_iter} iterations")


def _taylor_coeffs(f, x0: float, n: int) -> list:
    """
    Compute the first n+1 Taylor coefficients a_k = f^(k)(x0) / k!
    using iterated numerical differentiation.
    """
    coeffs = []
    h = 1e-4
    for k in range(n + 1):
        # k-th derivative via finite differences (central, order 2)
        # For small k this is acceptable
        dk = 0.0
        for j in range(k + 1):
            sign = (-1) ** (k - j)
            binom = math.comb(k, j)
            dk += sign * binom * f(x0 + j * h)
        dk /= h ** k
        coeffs.append(dk / math.factorial(k))
    return coeffs


# ══════════════════════════════════════════════════════════════════
#  OPERATION REGISTRY
# ══════════════════════════════════════════════════════════════════

_OPS = {}

def _op(name, aliases=None):
    def decorator(fn):
        _OPS[name] = fn
        for alias in (aliases or []):
            _OPS[alias] = fn
        return fn
    return decorator


# ── Racines ────────────────────────────────────────────────────────

@_op("sqrt", ["√"])
def op_sqrt(args):
    """sqrt <x> [n=2] — racine n-ième de x (défaut : racine carrée)"""
    if not args:
        raise ValueError("sqrt requires at least 1 argument: sqrt <x> [n]")
    x = _parse_float(args[0], "x")
    n = _parse_float(args[1], "n") if len(args) > 1 else 2.0
    if n == 0:
        raise ValueError("Root degree n cannot be 0")
    if x < 0 and n % 2 == 1:
        return "-" + _fmt((-x) ** (1 / n))
    if x < 0:
        result = complex(x) ** (1 / n)
        return _fmt(result)
    return _fmt(x ** (1 / n))


@_op("cbrt", ["∛"])
def op_cbrt(args):
    """cbrt <x> — racine cubique (gère les négatifs)"""
    if not args:
        raise ValueError("cbrt requires 1 argument")
    x = _parse_float(args[0], "x")
    return _fmt(math.copysign(abs(x) ** (1 / 3), x))


# ── Puissances / logarithmes ───────────────────────────────────────

@_op("pow", ["^", "**"])
def op_pow(args):
    """pow <x> <n> — x à la puissance n"""
    if len(args) < 2:
        raise ValueError("pow requires 2 arguments: pow <x> <n>")
    return _fmt(_parse_float(args[0], "x") ** _parse_float(args[1], "n"))


@_op("log")
def op_log(args):
    """log <x> [base=e] — logarithme (défaut : ln)"""
    if not args:
        raise ValueError("log requires at least 1 argument")
    x = _parse_float(args[0], "x")
    if x <= 0:
        raise ValueError("log requires x > 0")
    if len(args) > 1:
        base = _parse_float(args[1], "base")
        if base <= 0 or base == 1:
            raise ValueError("log base must be > 0 and ≠ 1")
        return _fmt(math.log(x, base))
    return _fmt(math.log(x))


@_op("log2")
def op_log2(args):
    """log2 <x> — logarithme base 2"""
    if not args: raise ValueError("log2 requires 1 argument")
    x = _parse_float(args[0], "x")
    if x <= 0: raise ValueError("log2 requires x > 0")
    return _fmt(math.log2(x))


@_op("log10")
def op_log10(args):
    """log10 <x> — logarithme base 10"""
    if not args: raise ValueError("log10 requires 1 argument")
    x = _parse_float(args[0], "x")
    if x <= 0: raise ValueError("log10 requires x > 0")
    return _fmt(math.log10(x))


@_op("exp")
def op_exp(args):
    """exp <x> — e^x"""
    if not args: raise ValueError("exp requires 1 argument")
    return _fmt(math.exp(_parse_float(args[0], "x")))


# ── Trigonométrie ──────────────────────────────────────────────────

def _trig(fn, args, name):
    if not args: raise ValueError(f"{name} requires 1 argument")
    x = _parse_float(args[0], "x")
    if len(args) > 1 and args[1].lower() == "deg":
        x = math.radians(x)
    return _fmt(fn(x))

def _atrig(fn, args, name):
    if not args: raise ValueError(f"{name} requires 1 argument")
    x = _parse_float(args[0], "x")
    r = fn(x)
    if len(args) > 1 and args[1].lower() == "deg":
        r = math.degrees(r)
    return _fmt(r)

@_op("sin")
def op_sin(args):
    """sin <x> [deg] — sinus (rad par défaut)"""
    return _trig(math.sin, args, "sin")

@_op("cos")
def op_cos(args):
    """cos <x> [deg] — cosinus"""
    return _trig(math.cos, args, "cos")

@_op("tan")
def op_tan(args):
    """tan <x> [deg] — tangente"""
    return _trig(math.tan, args, "tan")

@_op("asin")
def op_asin(args):
    """asin <x> [deg] — arc sinus"""
    return _atrig(math.asin, args, "asin")

@_op("acos")
def op_acos(args):
    """acos <x> [deg] — arc cosinus"""
    return _atrig(math.acos, args, "acos")

@_op("atan")
def op_atan(args):
    """atan <x> [deg] — arc tangente"""
    return _atrig(math.atan, args, "atan")

@_op("atan2")
def op_atan2(args):
    """atan2 <y> <x> [deg] — arc tangente 4 quadrants"""
    if len(args) < 2: raise ValueError("atan2 requires 2 arguments")
    y = _parse_float(args[0], "y")
    x = _parse_float(args[1], "x")
    r = math.atan2(y, x)
    if len(args) > 2 and args[2].lower() == "deg":
        r = math.degrees(r)
    return _fmt(r)


# ── Hyperboliques ──────────────────────────────────────────────────

@_op("sinh")
def op_sinh(args):
    """sinh <x> — sinus hyperbolique"""
    if not args: raise ValueError("sinh requires 1 argument")
    return _fmt(math.sinh(_parse_float(args[0], "x")))

@_op("cosh")
def op_cosh(args):
    """cosh <x> — cosinus hyperbolique"""
    if not args: raise ValueError("cosh requires 1 argument")
    return _fmt(math.cosh(_parse_float(args[0], "x")))

@_op("tanh")
def op_tanh(args):
    """tanh <x> — tangente hyperbolique"""
    if not args: raise ValueError("tanh requires 1 argument")
    return _fmt(math.tanh(_parse_float(args[0], "x")))

@_op("asinh")
def op_asinh(args):
    """asinh <x> — arc sinus hyperbolique"""
    if not args: raise ValueError("asinh requires 1 argument")
    return _fmt(math.asinh(_parse_float(args[0], "x")))

@_op("acosh")
def op_acosh(args):
    """acosh <x> — arc cosinus hyperbolique"""
    if not args: raise ValueError("acosh requires 1 argument")
    return _fmt(math.acosh(_parse_float(args[0], "x")))

@_op("atanh")
def op_atanh(args):
    """atanh <x> — arc tangente hyperbolique"""
    if not args: raise ValueError("atanh requires 1 argument")
    return _fmt(math.atanh(_parse_float(args[0], "x")))


# ── Arithmétique ───────────────────────────────────────────────────

@_op("abs")
def op_abs(args):
    """abs <x> — valeur absolue"""
    if not args: raise ValueError("abs requires 1 argument")
    return _fmt(abs(_parse_float(args[0], "x")))

@_op("ceil")
def op_ceil(args):
    """ceil <x> — plafond"""
    if not args: raise ValueError("ceil requires 1 argument")
    return _fmt(math.ceil(_parse_float(args[0], "x")))

@_op("floor")
def op_floor(args):
    """floor <x> — plancher"""
    if not args: raise ValueError("floor requires 1 argument")
    return _fmt(math.floor(_parse_float(args[0], "x")))

@_op("round")
def op_round(args):
    """round <x> [n=0] — arrondi à n décimales"""
    if not args: raise ValueError("round requires 1 argument")
    x = _parse_float(args[0], "x")
    n = int(_parse_float(args[1], "n")) if len(args) > 1 else 0
    return _fmt(round(x, n))

@_op("mod", ["%"])
def op_mod(args):
    """mod <x> <y> — x modulo y"""
    if len(args) < 2: raise ValueError("mod requires 2 arguments")
    x = _parse_float(args[0], "x")
    y = _parse_float(args[1], "y")
    if y == 0: raise ZeroDivisionError("modulo by zero")
    return _fmt(x % y)

@_op("div")
def op_div(args):
    """div <x> <y> — division entière"""
    if len(args) < 2: raise ValueError("div requires 2 arguments")
    x = _parse_float(args[0], "x")
    y = _parse_float(args[1], "y")
    if y == 0: raise ZeroDivisionError("division by zero")
    return _fmt(x // y)

@_op("gcd")
def op_gcd(args):
    """gcd <a> <b> — plus grand commun diviseur"""
    if len(args) < 2: raise ValueError("gcd requires 2 arguments")
    return _fmt(math.gcd(int(_parse_float(args[0])), int(_parse_float(args[1]))))

@_op("lcm")
def op_lcm(args):
    """lcm <a> <b> — plus petit commun multiple"""
    if len(args) < 2: raise ValueError("lcm requires 2 arguments")
    a = int(_parse_float(args[0]))
    b = int(_parse_float(args[1]))
    return _fmt(abs(a * b) // math.gcd(a, b) if a and b else 0)

@_op("fact", ["factorial", "!"])
def op_fact(args):
    """fact <n> — factorielle de n"""
    if not args: raise ValueError("fact requires 1 argument")
    n = int(_parse_float(args[0], "n"))
    if n < 0: raise ValueError("factorial requires n >= 0")
    return _fmt(math.factorial(n))

@_op("sign")
def op_sign(args):
    """sign <x> — signe de x (-1, 0, ou 1)"""
    if not args: raise ValueError("sign requires 1 argument")
    x = _parse_float(args[0], "x")
    return _fmt(1 if x > 0 else -1 if x < 0 else 0)

@_op("hypot")
def op_hypot(args):
    """hypot <a> <b> [c ...] — hypoténuse √(a²+b²+...)"""
    if len(args) < 2: raise ValueError("hypot requires at least 2 arguments")
    vals = [_parse_float(a) for a in args]
    return _fmt(math.hypot(*vals))

@_op("clamp")
def op_clamp(args):
    """clamp <x> <min> <max> — borne x dans [min, max]"""
    if len(args) < 3: raise ValueError("clamp requires 3 arguments: clamp <x> <min> <max>")
    x   = _parse_float(args[0], "x")
    lo  = _parse_float(args[1], "min")
    hi  = _parse_float(args[2], "max")
    return _fmt(max(lo, min(hi, x)))


# ── Combinatoire / théorie des nombres ─────────────────────────────

@_op("comb", ["C", "nCr"])
def op_comb(args):
    """comb <n> <k> — combinaison C(n,k) = n! / (k!(n-k)!)"""
    if len(args) < 2: raise ValueError("comb requires 2 arguments: comb <n> <k>")
    n = int(_parse_float(args[0], "n"))
    k = int(_parse_float(args[1], "k"))
    return _fmt(math.comb(n, k))

@_op("perm", ["P", "nPr"])
def op_perm(args):
    """perm <n> <k> — arrangement P(n,k) = n! / (n-k)!"""
    if len(args) < 2: raise ValueError("perm requires 2 arguments: perm <n> <k>")
    n = int(_parse_float(args[0], "n"))
    k = int(_parse_float(args[1], "k"))
    return _fmt(math.perm(n, k))

@_op("fib", ["fibonacci"])
def op_fib(args):
    """fib <n> — n-ième terme de la suite de Fibonacci (F(0)=0, F(1)=1)"""
    if not args: raise ValueError("fib requires 1 argument")
    n = int(_parse_float(args[0], "n"))
    if n < 0: raise ValueError("fib requires n >= 0")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return _fmt(a)

@_op("isprime")
def op_isprime(args):
    """isprime <n> — teste si n est premier"""
    if not args: raise ValueError("isprime requires 1 argument")
    n = int(_parse_float(args[0], "n"))
    if n < 2: return "false"
    if n == 2: return "true"
    if n % 2 == 0: return "false"
    for i in range(3, int(n ** 0.5) + 1, 2):
        if n % i == 0: return "false"
    return "true"

@_op("gamma", ["Γ"])
def op_gamma(args):
    """gamma <x> — fonction gamma Γ(x) = (x-1)! pour entiers"""
    if not args: raise ValueError("gamma requires 1 argument")
    x = _parse_float(args[0], "x")
    return _fmt(math.gamma(x))

@_op("beta")
def op_beta(args):
    """beta <a> <b> — fonction bêta B(a,b) = Γ(a)Γ(b)/Γ(a+b)"""
    if len(args) < 2: raise ValueError("beta requires 2 arguments")
    a = _parse_float(args[0], "a")
    b = _parse_float(args[1], "b")
    return _fmt(math.exp(math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)))


# ── Statistiques ────────────────────────────────────────────────────

@_op("sum")
def op_sum(args):
    """sum <x1> <x2> ... — somme"""
    if not args: raise ValueError("sum requires at least 1 argument")
    return _fmt(sum(_parse_float(a) for a in args))

@_op("avg", ["mean"])
def op_avg(args):
    """avg <x1> <x2> ... — moyenne arithmétique"""
    if not args: raise ValueError("avg requires at least 1 argument")
    vals = [_parse_float(a) for a in args]
    return _fmt(sum(vals) / len(vals))

@_op("median")
def op_median(args):
    """median <x1> <x2> ... — médiane"""
    if not args: raise ValueError("median requires at least 1 argument")
    vals = sorted(_parse_float(a) for a in args)
    n = len(vals)
    mid = n // 2
    return _fmt(vals[mid] if n % 2 == 1 else (vals[mid - 1] + vals[mid]) / 2)

@_op("variance", ["var"])
def op_variance(args):
    """variance <x1> <x2> ... — variance (population)"""
    if not args: raise ValueError("variance requires at least 1 argument")
    vals = [_parse_float(a) for a in args]
    m = sum(vals) / len(vals)
    return _fmt(sum((v - m) ** 2 for v in vals) / len(vals))

@_op("stddev", ["std"])
def op_stddev(args):
    """stddev <x1> <x2> ... — écart-type (population)"""
    if not args: raise ValueError("stddev requires at least 1 argument")
    vals = [_parse_float(a) for a in args]
    m = sum(vals) / len(vals)
    return _fmt(math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)))

@_op("min")
def op_min(args):
    """min <x1> <x2> ... — minimum"""
    if not args: raise ValueError("min requires at least 1 argument")
    return _fmt(min(_parse_float(a) for a in args))

@_op("max")
def op_max(args):
    """max <x1> <x2> ... — maximum"""
    if not args: raise ValueError("max requires at least 1 argument")
    return _fmt(max(_parse_float(a) for a in args))

@_op("range", ["span"])
def op_range(args):
    """range <x1> <x2> ... — étendue (max - min)"""
    if not args: raise ValueError("range requires at least 1 argument")
    vals = [_parse_float(a) for a in args]
    return _fmt(max(vals) - min(vals))


# ── Calcul différentiel / intégral ────────────────────────────────

@_op("deriv", ["d", "derivative"])
def op_deriv(args):
    """deriv <expr> <x> [order=1] — dérivée numérique d'une expression en x"""
    if len(args) < 2:
        raise ValueError("deriv requires: deriv <expr> <x> [order=1]\n"
                         "  ex: deriv x^2 3         → 6\n"
                         "  ex: deriv sin(x) 0 2    → second derivative")
    expr  = args[0]
    x_val = _parse_float(args[1], "x")
    order = int(_parse_float(args[2], "order")) if len(args) > 2 else 1

    f = lambda x: _eval_expr(expr, x)

    if order == 1:
        return _fmt(_num_deriv(f, x_val))
    elif order == 2:
        return _fmt(_num_deriv2(f, x_val))
    else:
        # Iterated first-order derivatives for higher orders
        g = f
        for _ in range(order):
            _g = g
            g = lambda x, _g=_g: _num_deriv(_g, x)
        return _fmt(g(x_val))


@_op("integral", ["integrate", "∫"])
def op_integral(args):
    """integral <expr> <a> <b> [n=1000] — intégrale définie de a à b"""
    if len(args) < 3:
        raise ValueError("integral requires: integral <expr> <a> <b> [n]\n"
                         "  ex: integral x^2 0 3       → 9\n"
                         "  ex: integral sin(x) 0 pi   → 2")
    expr = args[0]
    a    = _parse_float(args[1], "a")
    b    = _parse_float(args[2], "b")
    n    = int(_parse_float(args[3], "n")) if len(args) > 3 else 1000

    f = lambda x: _eval_expr(expr, x)
    return _fmt(_simpson(f, a, b, n))


@_op("limit")
def op_limit(args):
    """limit <expr> <x> — limite numérique approchée en x (approche par les deux côtés)"""
    if len(args) < 2:
        raise ValueError("limit requires: limit <expr> <x>\n"
                         "  ex: limit sin(x)/x 0   → 1  (approx)")
    expr  = args[0]
    x_val = _parse_float(args[1], "x")
    h     = 1e-9

    f = lambda x: _eval_expr(expr, x)
    try:
        left  = f(x_val - h)
        right = f(x_val + h)
        if abs(left - right) < 1e-6:
            return _fmt((left + right) / 2)
        return f"left={_fmt(left)}, right={_fmt(right)}  (discontinuous)"
    except Exception:
        return _fmt(f(x_val))


@_op("root", ["solve", "zero"])
def op_root(args):
    """root <expr> <x0> — racine de f(x)=0 par Newton-Raphson depuis x0"""
    if len(args) < 2:
        raise ValueError("root requires: root <expr> <x0>\n"
                         "  ex: root x^2-4 1     → 2\n"
                         "  ex: root cos(x)-x 1  → 0.739085 (point fixe cos)")
    expr = args[0]
    x0   = _parse_float(args[1], "x0")
    f    = lambda x: _eval_expr(expr, x)
    return _fmt(_find_root_newton(f, x0))


@_op("taylor")
def op_taylor(args):
    """taylor <expr> <x0> <n> [x=x0] — développement de Taylor d'ordre n en x0"""
    if len(args) < 3:
        raise ValueError("taylor requires: taylor <expr> <x0> <n> [x]\n"
                         "  ex: taylor sin(x) 0 5    → coefficients a0..a5\n"
                         "  ex: taylor sin(x) 0 5 1  → valeur approchée en x=1")
    expr = args[0]
    x0   = _parse_float(args[1], "x0")
    n    = int(_parse_float(args[2], "n"))
    f    = lambda x: _eval_expr(expr, x)

    coeffs = _taylor_coeffs(f, x0, n)

    if len(args) > 3:
        # Evaluate the Taylor polynomial at x
        x_eval = _parse_float(args[3], "x")
        val = sum(c * (x_eval - x0) ** k for k, c in enumerate(coeffs))
        return _fmt(val)
    else:
        # Return coefficients
        parts = []
        for k, c in enumerate(coeffs):
            cv = round(c, 8)
            if cv == 0:
                continue
            if k == 0:
                parts.append(_fmt(cv))
            elif k == 1:
                parts.append(f"{_fmt(cv)}*(x-{_fmt(x0)})")
            else:
                parts.append(f"{_fmt(cv)}*(x-{_fmt(x0)})^{k}")
        return " + ".join(parts) if parts else "0"


# ── Constantes ────────────────────────────────────────────────────

@_op("pi")
def op_pi(args):
    """pi — π ≈ 3.14159265..."""
    return _fmt(math.pi)

@_op("e_const", ["euler"])
def op_e_const(args):
    """e — e ≈ 2.71828182..."""
    return _fmt(math.e)

@_op("phi", ["golden"])
def op_phi(args):
    """phi — nombre d'or φ = (1+√5)/2 ≈ 1.61803..."""
    return _fmt((1 + math.sqrt(5)) / 2)

@_op("tau")
def op_tau(args):
    """tau — τ = 2π ≈ 6.28318..."""
    return _fmt(math.tau)


# ── Conversions ───────────────────────────────────────────────────

@_op("deg2rad", ["d2r"])
def op_deg2rad(args):
    """deg2rad <x> — degrés → radians"""
    if not args: raise ValueError("deg2rad requires 1 argument")
    return _fmt(math.radians(_parse_float(args[0], "x")))

@_op("rad2deg", ["r2d"])
def op_rad2deg(args):
    """rad2deg <x> — radians → degrés"""
    if not args: raise ValueError("rad2deg requires 1 argument")
    return _fmt(math.degrees(_parse_float(args[0], "x")))

@_op("hex2dec")
def op_hex2dec(args):
    """hex2dec <hex> — hexadécimal → décimal"""
    if not args: raise ValueError("hex2dec requires 1 argument")
    try: return str(int(args[0], 16))
    except ValueError: raise ValueError(f"Invalid hex: {args[0]!r}")

@_op("dec2hex")
def op_dec2hex(args):
    """dec2hex <n> — décimal → hexadécimal"""
    if not args: raise ValueError("dec2hex requires 1 argument")
    return hex(int(_parse_float(args[0], "n")))

@_op("dec2bin")
def op_dec2bin(args):
    """dec2bin <n> — décimal → binaire"""
    if not args: raise ValueError("dec2bin requires 1 argument")
    return bin(int(_parse_float(args[0], "n")))

@_op("bin2dec")
def op_bin2dec(args):
    """bin2dec <bin> — binaire → décimal"""
    if not args: raise ValueError("bin2dec requires 1 argument")
    try: return str(int(args[0], 2))
    except ValueError: raise ValueError(f"Invalid binary: {args[0]!r}")

@_op("dec2oct")
def op_dec2oct(args):
    """dec2oct <n> — décimal → octal"""
    if not args: raise ValueError("dec2oct requires 1 argument")
    return oct(int(_parse_float(args[0], "n")))

@_op("oct2dec")
def op_oct2dec(args):
    """oct2dec <oct> — octal → décimal"""
    if not args: raise ValueError("oct2dec requires 1 argument")
    try: return str(int(args[0], 8))
    except ValueError: raise ValueError(f"Invalid octal: {args[0]!r}")


# ── Évaluation d'expression libre ────────────────────────────────

@_op("eval", ["=", "calc"])
def op_eval(args):
    """eval <expr> [x=val] — évalue une expression mathématique"""
    if not args:
        raise ValueError("eval requires an expression\n"
                         "  ex: eval 2^10\n"
                         "  ex: eval sin(pi/6)\n"
                         "  ex: eval x^2+1 x=3")
    # Detect x=val pattern
    x_val = None
    expr_parts = []
    for tok in args:
        if tok.startswith("x="):
            try:
                x_val = float(tok[2:])
            except ValueError:
                raise ValueError(f"Invalid x value: {tok!r}")
        else:
            expr_parts.append(tok)
    expr = "".join(expr_parts)
    return _fmt(_eval_expr(expr, x=x_val))


# ══════════════════════════════════════════════════════════════════
#  R_ECO3 INTERFACE
# ══════════════════════════════════════════════════════════════════

_CATEGORIES = [
    ("Roots",           ["sqrt", "cbrt"]),
    ("Powers / Log",    ["pow", "log", "log2", "log10", "exp"]),
    ("Trigonometry",    ["sin", "cos", "tan", "asin", "acos", "atan", "atan2"]),
    ("Hyperbolic",      ["sinh", "cosh", "tanh", "asinh", "acosh", "atanh"]),
    ("Arithmetic",      ["abs", "ceil", "floor", "round", "mod", "div",
                         "gcd", "lcm", "fact", "sign", "hypot", "clamp"]),
    ("Combinatorics",   ["comb", "perm", "fib", "isprime", "gamma", "beta"]),
    ("Statistics",      ["sum", "avg", "median", "variance", "stddev",
                         "min", "max", "range"]),
    ("Calculus",        ["deriv", "integral", "limit", "root", "taylor"]),
    ("Constants",       ["pi", "e_const", "phi", "tau"]),
    ("Conversions",     ["deg2rad", "rad2deg",
                         "hex2dec", "dec2hex", "dec2bin", "bin2dec",
                         "dec2oct", "oct2dec"]),
    ("Expression",      ["eval"]),
]


def R_ECO3(args: str, log_fn=print):
    import core
    pos, _ = core.utils.parse_command(args)

    if pos[0] in ("help", "?", "h"):
        log_fn("[bold cyan]prism[/bold cyan] — mathematical functions\n")
        log_fn("  [dim]Usage:[/dim]  prism <operation> [args...]\n")
        seen = set()
        for category, ops in _CATEGORIES:
            log_fn(f"  [bold white]{category}[/bold white]")
            for name in ops:
                fn = _OPS.get(name)
                if fn and fn not in seen:
                    seen.add(fn)
                    doc = (fn.__doc__ or "").strip().split("\n")[0]
                    log_fn(f"    [cyan]{name:<14}[/cyan] [dim]{doc}[/dim]")
            log_fn("")
        return 0

    op_name = pos[0].lower()
    # alias: bare 'e' maps to e_const to avoid clash with expression token
    if op_name == "e":
        op_name = "e_const"

    op_args = pos[1:]
    fn = _OPS.get(op_name)

    if fn is None:
        log_fn(f"[bold red]  ✗[/bold red]  Unknown operation: [bold]{op_name}[/bold]")
        log_fn("      Type [bold cyan]prism help[/bold cyan] for the list of operations.")
        return 1

    try:
        result = fn(op_args)
        log_fn(f"[bold green]  =[/bold green]  [bold white]{result}[/bold white]")
        return 0, result
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        log_fn(f"[bold red]  ✗[/bold red]  {exc}")
        return 1


# ══════════════════════════════════════════════════════════════════
#  METADATA
# ══════════════════════════════════════════════════════════════════

def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.utils", ("1.1",)),
        )
    )


def R_ECO3inf():
    return {
        "name":        "prism",
        "desc":        "Mathematical functions — roots, powers, trig, hyperbolic, calculus, stats, combinatorics, conversions",
        "help":        "Decompose and transform numbers. Full suite: roots, powers, logarithms, trigonometry, hyperbolic, differential/integral calculus, combinatorics, statistics, base conversions, and free expression evaluation.",
        "version_mod": "1.1",
        "L2Module":    True,
        "alias_rules": "prism /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "manual": (
            "prism — Mathematical functions module  v1.1\n"
            "==========================================\n"
            "\n"
            "SYNOPSIS\n"
            "    prism <operation> [args...]\n"
            "\n"
            "DESCRIPTION\n"
            "    Provides roots, powers, logarithms, trigonometry, hyperbolic functions,\n"
            "    arithmetic helpers, combinatorics, statistics, calculus tools, conversions,\n"
            "    and free expression evaluation.\n"
            "\n"
            "COMMANDS\n"
            "    sqrt <x> [n=2]\n"
            "        N-th root of x.\n"
            "\n"
            "    cbrt <x>\n"
            "        Cube root of x.\n"
            "\n"
            "    pow <x> <n>\n"
            "        Raises x to the power n.\n"
            "\n"
            "    log <x> [base=e]\n"
            "    log2 <x>\n"
            "    log10 <x>\n"
            "    exp <x>\n"
            "        Logarithms and exponential.\n"
            "\n"
            "    sin <x> [deg]\n"
            "    cos <x> [deg]\n"
            "    tan <x> [deg]\n"
            "    asin <x> [deg]\n"
            "    acos <x> [deg]\n"
            "    atan <x> [deg]\n"
            "    atan2 <y> <x> [deg]\n"
            "        Trigonometric operations.\n"
            "\n"
            "    sinh <x>\n"
            "    cosh <x>\n"
            "    tanh <x>\n"
            "    asinh <x>\n"
            "    acosh <x>\n"
            "    atanh <x>\n"
            "        Hyperbolic operations.\n"
            "\n"
            "    abs <x>\n"
            "    ceil <x>\n"
            "    floor <x>\n"
            "    round <x> [n=0]\n"
            "    mod <x> <y>\n"
            "    div <x> <y>\n"
            "    gcd <a> <b>\n"
            "    lcm <a> <b>\n"
            "    fact <n>\n"
            "    sign <x>\n"
            "    hypot <a> <b> [c ...]\n"
            "    clamp <x> <min> <max>\n"
            "        Arithmetic helpers.\n"
            "\n"
            "    comb <n> <k>\n"
            "    perm <n> <k>\n"
            "    fib <n>\n"
            "    isprime <n>\n"
            "    gamma <x>\n"
            "    beta <a> <b>\n"
            "        Combinatorics and number theory.\n"
            "\n"
            "    sum <x1> <x2> ...\n"
            "    avg <x1> <x2> ...\n"
            "    median <x1> <x2> ...\n"
            "    variance <x1> <x2> ...\n"
            "    stddev <x1> <x2> ...\n"
            "    min <x1> <x2> ...\n"
            "    max <x1> <x2> ...\n"
            "    range <x1> <x2> ...\n"
            "        Statistics helpers.\n"
            "\n"
            "    deriv <expr> <x> [order=1]\n"
            "    integral <expr> <a> <b> [n=1000]\n"
            "    limit <expr> <x>\n"
            "    root <expr> <x0>\n"
            "    taylor <expr> <x0> <n> [x]\n"
            "        Numerical calculus tools.\n"
            "\n"
            "    pi\n"
            "    e\n"
            "    phi\n"
            "    tau\n"
            "        Mathematical constants.\n"
            "\n"
            "    deg2rad <x>\n"
            "    rad2deg <x>\n"
            "    hex2dec <hex>\n"
            "    dec2hex <n>\n"
            "    dec2bin <n>\n"
            "    bin2dec <bin>\n"
            "    dec2oct <n>\n"
            "    oct2dec <oct>\n"
            "        Conversions.\n"
            "\n"
            "    eval <expr> [x=val]\n"
            "        Evaluates a free mathematical expression.\n"
            "\n"
            "EXAMPLES\n"
            "    prism sqrt 9\n"
            "    prism deriv x^2 3\n"
            "    prism integral sin(x) 0 pi\n"
            "    prism eval x^2+1 x=5\n"
        ),
    }