"""
Module beaver — Interpréteur et compilateur de modules .bvr
Version 1.0 · R-ECO3 v3.5.1b · Codename Ant
"""

import re
import sys
import ast
import os


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_value(raw: str, var: dict, context: dict) -> object:
    """
    Resolve a raw token to its Python value.
    Handles: $p:N, $k:key, string literals, numeric literals, base identifiers,
    and plain variable names.
    """
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]

    if re.fullmatch(r"-?\d+", raw):
        return int(raw)

    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)

    if raw.startswith("$p:"):
        idx = int(raw[3:])
        positional = context.get("positional", [])
        return positional[idx] if idx < len(positional) else ""

    if raw.startswith("$k:"):
        key = raw[3:]
        return context.get("keywords", {}).get(key, "")

    # base identifiers injected by R-ECO
    if raw in ("log", "args", "hive", "apix"):
        return context.get(raw)

    # variable
    if raw in var:
        return var[raw]

    raise RCSError(f"BVR010: Variable non définie : {raw}")


def _parse_args_string(args_str: str):
    """
    Parse the raw args string (positional + --key=val / --key val) into
    (positional: list, keywords: dict).
    """
    positional = []
    keywords = {}
    if not args_str:
        return positional, keywords
    tokens = args_str.split()
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith("--"):
            kv = t[2:]
            if "=" in kv:
                k, v = kv.split("=", 1)
                keywords[k] = v
            else:
                # --key val
                keywords[kv] = tokens[i + 1] if i + 1 < len(tokens) else "true"
                i += 1
        else:
            positional.append(t)
        i += 1
    return positional, keywords


def _coerce(val):
    """Try to keep numbers as numbers, else string."""
    if isinstance(val, (int, float)):
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        pass
    try:
        return float(val)
    except (ValueError, TypeError):
        pass
    return val


class RCSError(Exception):
    pass


# ---------------------------------------------------------------------------
# Main RCS interpreter
# ---------------------------------------------------------------------------

class RCS:
    def __init__(self, code: str, context: dict = None):
        """
        code    : raw RCS source (string)
        context : dict with keys: log, args, hive, apix, __beaver__
                  'args' is the raw argument string passed to the module.
        """
        raw_lines = code.split("\n")
        self.lines = [l.rstrip() for l in raw_lines]
        self.context = context or {}

        # Parse raw args into positional / keyword lists
        raw_args = self.context.get("args", "")
        pos, kw = _parse_args_string(raw_args)
        self.context["positional"] = pos
        self.context["keywords"] = kw

        self.var: dict = {}          # variable store
        self.lastvar = None          # implicit result register
        self.lastcmp = None          # last comparison result
        self.lastcode = 0            # last > call return code
        self.lasterr = ""            # last > call error message

        # Build label index  {label_name: line_index}
        self.labels: dict[str, int] = {}
        for i, line in enumerate(self.lines):
            m = re.match(r"^(\w+):$", line.strip())
            if m:
                self.labels[m.group(1)] = i

        self.p = 0                   # program counter
        self._call_stack = []        # [(return_pc, saved_positional, saved_keywords)]

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def execute(self):
        """Run from line 0 (or from Start label if set externally)."""
        self.p = 0
        self._run_until(len(self.lines))
        return self.var.get("ret", self.lastvar)

    def call_label(self, label: str, *args):
        """Call a named label with positional arguments and return ret."""
        if label not in self.labels:
            raise RCSError(f"BVR014: Label introuvable : {label}")
        # Save state
        saved_pos = self.context.get("positional", [])
        saved_kw  = self.context.get("keywords", {})
        saved_pc  = self.p

        self.context["positional"] = [str(a) for a in args]
        self.context["keywords"] = {}
        self.p = self.labels[label] + 1

        self._run_until(len(self.lines), stop_on_ret=True)

        ret = self.var.get("ret", self.lastvar)

        # Restore state
        self.p = saved_pc
        self.context["positional"] = saved_pos
        self.context["keywords"] = saved_kw

        return ret

    # ------------------------------------------------------------------
    # Core execution loop
    # ------------------------------------------------------------------

    def _run_until(self, end: int, stop_on_ret: bool = False):
        while self.p < end:
            line = self.lines[self.p].strip()

            # Skip blank lines and comments
            if not line or line.startswith("#"):
                self.p += 1
                continue

            # Skip label declarations
            if re.match(r"^\w+:$", line):
                self.p += 1
                continue

            self._exec_line(line)
            self.p += 1

            if stop_on_ret and "ret" in self.var:
                break

    def _exec_line(self, line: str):
        tokens = self._tokenize(line)
        if not tokens:
            return
        cmd, *args = tokens

        match cmd:
            case "set":
                self._cmd_set(args)
            case "add":
                self._cmd_arith(args, "+")
            case "sub":
                self._cmd_arith(args, "-")
            case "mul":
                self._cmd_arith(args, "*")
            case "div":
                self._cmd_arith(args, "/")
            case ">":
                self._cmd_call_reco(args)
            case "cmp":
                self._cmd_cmp(args)
            case "if:":
                self._cmd_if()
            case "try:":
                self._cmd_try()
            case "hget":
                self._cmd_hget(args)
            case "hset":
                self._cmd_hset(args)
            case "hdel":
                self._cmd_hdel(args)
            case "call":
                self._cmd_call(args)
            case "setfn":
                self._cmd_setfn(args)
            case "log":
                self._cmd_log(args)
            case "exit":
                code = int(args[0]) if args else 0
                raise SystemExit(code)
            case _:
                raise RCSError(f"BVR011: Instruction inconnue : {cmd}")

    # ------------------------------------------------------------------
    # Tokenizer — respects quoted strings
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(line: str) -> list[str]:
        tokens = []
        current = []
        in_quote = False
        i = 0
        while i < len(line):
            c = line[i]
            if c == '"' and not in_quote:
                in_quote = True
                current.append(c)
            elif c == '"' and in_quote:
                in_quote = False
                current.append(c)
            elif c == ' ' and not in_quote:
                if current:
                    tokens.append("".join(current))
                    current = []
            else:
                current.append(c)
            i += 1
        if current:
            tokens.append("".join(current))
        return tokens

    # ------------------------------------------------------------------
    # Instruction implementations
    # ------------------------------------------------------------------

    def _cmd_set(self, args: list):
        if not args:
            raise RCSError("BVR011: set nécessite au moins un argument")
        varname = args[0]
        if len(args) >= 2:
            val = _parse_value(args[1], self.var, self.context)
        else:
            # set var  →  var = lastvar
            val = self.lastvar
        val = _coerce(val)
        self.var[varname] = val
        self.lastvar = val

    def _cmd_arith(self, args: list, op: str):
        if len(args) < 3:
            raise RCSError(f"BVR011: Arithmétique nécessite 3 arguments")
        dest = args[0]
        a = _coerce(_parse_value(args[1], self.var, self.context))
        b = _coerce(_parse_value(args[2], self.var, self.context))
        if op == "+" : result = a + b
        elif op == "-": result = a - b
        elif op == "*": result = a * b
        elif op == "/":
            if b == 0:
                raise RCSError("BVR012: Division par zéro")
            result = a / b
        self.var[dest] = result
        self.lastvar = result

    def _cmd_call_reco(self, args: list):
        """Execute a R-ECO command via apix."""
        apix = self.context.get("apix")
        log  = self.context.get("log", print)
        cmd  = " ".join(str(_parse_value(a, self.var, self.context)) for a in args)
        if apix is None:
            raise RCSError("BVR011: apix non disponible dans ce contexte")
        try:
            code, val = apix(f"run {cmd}", log)
        except Exception as e:
            self.lastcode = 1
            self.lasterr  = str(e)
            self.lastvar  = None
            return
        self.lastcode = code
        if code == 0:
            self.lastvar = val
            self.lasterr = ""
        else:
            self.lasterr = str(val)
            self.lastvar = None

    def _cmd_cmp(self, args: list):
        if len(args) < 3:
            raise RCSError("BVR011: cmp nécessite 3 arguments : a op b")
        a  = _coerce(_parse_value(args[0], self.var, self.context))
        op = args[1]
        b  = _coerce(_parse_value(args[2], self.var, self.context))
        match op:
            case "==": self.lastcmp = a == b
            case "!=": self.lastcmp = a != b
            case ">" : self.lastcmp = a >  b
            case "<" : self.lastcmp = a <  b
            case ">=": self.lastcmp = a >= b
            case "<=": self.lastcmp = a <= b
            case _:
                raise RCSError(f"BVR011: Opérateur cmp inconnu : {op}")
        self.var["lastcmp"] = self.lastcmp

    def _cmd_if(self):
        """Handle if: ... [else:] ... end block."""
        if self.lastcmp is None:
            raise RCSError("BVR013: if: sans cmp préalable")

        if_start  = self.p + 1
        else_line = None
        end_line  = None
        depth = 1
        i = self.p + 1
        while i < len(self.lines):
            t = self.lines[i].strip()
            if t == "if:":
                depth += 1
            elif t == "try:":
                depth += 1
            elif t == "else:" and depth == 1:
                else_line = i
            elif t == "end" and depth == 1:
                end_line = i
                break
            elif t == "end":
                depth -= 1
            i += 1

        if end_line is None:
            raise RCSError("BVR004: if: sans end correspondant")

        if self.lastcmp:
            branch_end = else_line if else_line else end_line
            self._exec_block(if_start, branch_end)
        elif else_line:
            self._exec_block(else_line + 1, end_line)

        self.p = end_line  # outer loop will +1

    def _cmd_try(self):
        """Handle try: ... except: ... end block."""
        try_start   = self.p + 1
        except_line = None
        end_line    = None
        depth = 1
        i = self.p + 1
        while i < len(self.lines):
            t = self.lines[i].strip()
            if t in ("if:", "try:"):
                depth += 1
            elif t == "except:" and depth == 1:
                except_line = i
            elif t == "end" and depth == 1:
                end_line = i
                break
            elif t == "end":
                depth -= 1
            i += 1

        if end_line is None:
            raise RCSError("BVR004: try: sans end correspondant")
        if except_line is None:
            raise RCSError("BVR004: try: sans except: correspondant")

        prev_code = self.lastcode
        self._exec_block(try_start, except_line)

        if self.lastcode == 1:
            self._exec_block(except_line + 1, end_line)

        self.p = end_line

    def _exec_block(self, start: int, end: int):
        """Execute lines [start, end) updating self.p internally."""
        saved_p = self.p
        self.p = start
        while self.p < end:
            line = self.lines[self.p].strip()
            if line and not line.startswith("#") and not re.match(r"^\w+:$", line):
                self._exec_line(line)
            self.p += 1
        self.p = saved_p

    def _cmd_hget(self, args: list):
        if len(args) < 2:
            raise RCSError("BVR011: hget nécessite 2 arguments")
        varname = args[0]
        key     = args[1]
        hive    = self.context.get("hive")
        if hive is None:
            raise RCSError("BVR011: hive non disponible dans ce contexte")
        val = hive.get(key)
        self.var[varname] = val
        self.lastvar = val

    def _cmd_hset(self, args: list):
        if len(args) < 2:
            raise RCSError("BVR011: hset nécessite 2 arguments")
        key     = args[0]
        val     = _parse_value(args[1], self.var, self.context)
        hive    = self.context.get("hive")
        if hive is None:
            raise RCSError("BVR011: hive non disponible dans ce contexte")
        hive.set(key, val)

    def _cmd_hdel(self, args: list):
        if not args:
            raise RCSError("BVR011: hdel nécessite 1 argument")
        hive = self.context.get("hive")
        if hive is None:
            raise RCSError("BVR011: hive non disponible dans ce contexte")
        hive.delete(args[0])

    def _cmd_call(self, args: list):
        """
        call label arg0 arg1 ...          → internal label
        call id:fn(arg0, arg1, ...)       → inter-script
        """
        if not args:
            raise RCSError("BVR011: call nécessite au moins 1 argument")

        target = args[0]

        # Inter-script call: "1:fnname" or "1:fnname(a, b)"
        interscript = re.match(r"^(\d+):(\w+)(?:\((.*)\))?$", target)
        if interscript:
            script_id = int(interscript.group(1))
            fn_name   = interscript.group(2)
            raw_inner = interscript.group(3) or ""
            raw_args_tokens = ([raw_inner] if raw_inner else []) + args[1:]
            call_args = self._resolve_call_args(raw_args_tokens)

            beaver = self.context.get("__beaver__")
            if beaver is None:
                raise RCSError("BVR015: __beaver__ non disponible pour appel inter-script")
            result = beaver.call(script_id, fn_name, *call_args)
            self.lastvar = result
            return

        # Internal label call: "label arg0 arg1 ..."
        label     = target
        call_args = self._resolve_call_args(args[1:])
        result    = self.call_label(label, *call_args)
        self.lastvar = result

    def _resolve_call_args(self, raw_tokens: list) -> list:
        """
        Parse comma-separated or space-separated argument tokens,
        resolving each to its Python value.
        """
        joined = " ".join(raw_tokens)
        parts  = [p.strip() for p in joined.split(",") if p.strip()]
        return [_parse_value(p, self.var, self.context) for p in parts]

    def _cmd_setfn(self, args: list):
        if len(args) < 2:
            raise RCSError("BVR011: setfn nécessite 2 arguments")
        alias  = args[0]
        source = args[1]
        fn = self.context.get(source) or self.var.get(source)
        if not callable(fn):
            raise RCSError(f"BVR011: setfn : {source} n'est pas une fonction")
        self.context[alias] = fn

    def _cmd_log(self, args: list):
        if not args:
            raise RCSError("BVR011: log nécessite 1 argument")
        val = _parse_value(args[0], self.var, self.context)
        log = self.context.get("log", print)
        log(str(val))


# ---------------------------------------------------------------------------
# .bvr parser
# ---------------------------------------------------------------------------

BVRSEP = "|BVRSEP|"
BVRSEP_ESC = "/|BVRSEP|"


def _unescape_bvrsep(text: str) -> str:
    """Replace escaped /|BVRSEP| with literal |BVRSEP|."""
    return text.replace(BVRSEP_ESC, BVRSEP)


def parse_bvr(source: str) -> dict:
    """
    Parse a .bvr source string.
    Returns a dict:
        {
            "name": str,
            "desc": str,
            "version": str,
            "help": str,            # optional
            "manual": str,          # optional
            "dependance": str,      # optional raw string
            "start": str,           # optional, default "0:R_ECO3"
            "scripts": {
                id (int): {"lang": str, "version": str, "code": str}
            }
        }
    Raises BeaverError on parse errors.
    """
    lines = source.split("\n")

    # --- magic check ---
    if not lines or lines[0].strip() != "#BEAVER1":
        raise BeaverError("BVR001: Magic #BEAVER1 absent ou invalide")

    result = {
        "name": None,
        "desc": None,
        "version": None,
        "help": "",
        "manual": "",
        "dependance": "",
        "start": "0:R_ECO3",
        "scripts": {},
    }

    i = 1
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # blank or comment
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Script block
        script_header = re.match(
            r'^Script\s+\|BVRSEP\|lang=(\w+),\s*version=([^,|]+),\s*id=(\d+)\|BVRSEP\|$',
            stripped
        )
        if script_header:
            lang    = script_header.group(1)
            ver     = script_header.group(2).strip()
            sid     = int(script_header.group(3))

            if lang not in ("py", "rcs"):
                raise BeaverError(f"BVR007: lang inconnu : {lang}")
            if sid in result["scripts"]:
                raise BeaverError(f"BVR005: Script id={sid} dupliqué")

            # Collect content until closing |BVRSEP| on its own line
            i += 1
            code_lines = []
            while i < n:
                if lines[i].strip() == BVRSEP:
                    break
                code_lines.append(_unescape_bvrsep(lines[i]))
                i += 1
            else:
                raise BeaverError(f"BVR004: Script id={sid} non fermé")

            result["scripts"][sid] = {
                "lang": lang,
                "version": ver,
                "code": "\n".join(code_lines),
            }
            i += 1
            continue

        # Manual block
        m_manual = re.match(r'^Manual\s*=\s*\|BVRSEP\|$', stripped)
        if m_manual:
            i += 1
            manual_lines = []
            while i < n:
                if lines[i].strip() == BVRSEP:
                    break
                manual_lines.append(_unescape_bvrsep(lines[i]))
                i += 1
            else:
                raise BeaverError("BVR004: Bloc Manual non fermé")
            result["manual"] = "\n".join(manual_lines)
            i += 1
            continue

        # Key = "value" fields
        kv = re.match(r'^(\w+)\s*=\s*"(.*)"$', stripped)
        if kv:
            key = kv.group(1).lower()
            val = kv.group(2)
            if key in ("name", "desc", "version", "help", "start"):
                result[key] = val
            i += 1
            continue

        # Dependance = ... (raw tuple-like, no quotes around full value)
        dep = re.match(r'^Dependance\s*=\s*(.+)$', stripped)
        if dep:
            result["dependance"] = dep.group(1).strip()
            i += 1
            continue

        i += 1

    # Validate mandatory fields
    for field in ("name", "desc", "version"):
        if not result[field]:
            raise BeaverError(f"BVR002: Champ obligatoire absent : {field}")

    # Validate Start format
    if not re.match(r'^\d+:\w+$', result["start"]):
        raise BeaverError(f"BVR006: Start mal formé : {result['start']}")

    return result


def parse_bvr_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return parse_bvr(f.read())


# ---------------------------------------------------------------------------
# BeaverError
# ---------------------------------------------------------------------------

class BeaverError(Exception):
    pass


# ---------------------------------------------------------------------------
# BeaverInstance — multi-script dispatcher
# ---------------------------------------------------------------------------

class BeaverInstance:
    """
    Wraps a parsed .bvr dict and provides:
      - execute(args, log_fn, hive, apix) → (code, value)
      - call(script_id, fn_name, *args)   → value
    """

    def __init__(self, bvr: dict, hive=None, apix=None, log_fn=None):
        self.bvr    = bvr
        self.hive   = hive
        self.apix   = apix
        self.log_fn = log_fn or print

        # Cache of compiled Python namespaces {id: namespace}
        self._py_ns: dict[int, dict] = {}

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    def execute(self, args: str = "", log_fn=None, hive=None, apix=None):
        """
        Run the module's Start function.
        Returns (0, value) on success, (1, error_message) on failure.
        """
        log  = log_fn or self.log_fn
        hive = hive or self.hive
        apix = apix or self.apix

        start_str = self.bvr["start"]
        sid_str, fn_name = start_str.split(":", 1)
        sid = int(sid_str)

        try:
            result = self.call(sid, fn_name, args, log, hive, apix)
            return (0, result)
        except SystemExit as e:
            code = e.code if e.code is not None else 0
            return (code, None)
        except BeaverError as e:
            return (1, str(e))
        except RCSError as e:
            return (1, str(e))
        except Exception as e:
            return (1, f"BVR020: {e}")

    # ------------------------------------------------------------------
    # Public: inter-script call
    # ------------------------------------------------------------------

    def call(self, script_id: int, fn_name: str, *args):
        """
        Call fn_name in script script_id with *args.
        Returns the function's return value.
        """
        scripts = self.bvr["scripts"]
        if script_id not in scripts:
            raise BeaverError(f"BVR015: Script id={script_id} introuvable")

        script = scripts[script_id]
        lang   = script["lang"]

        if lang == "py":
            return self._call_py(script_id, fn_name, *args)
        elif lang == "rcs":
            return self._call_rcs(script_id, fn_name, *args)
        else:
            raise BeaverError(f"BVR007: lang inconnu : {lang}")

    # ------------------------------------------------------------------
    # Python script execution
    # ------------------------------------------------------------------

    def _get_py_namespace(self, script_id: int) -> dict:
        """Compile and cache the Python namespace for script_id."""
        if script_id in self._py_ns:
            return self._py_ns[script_id]

        script = self.bvr["scripts"][script_id]
        ns = {
            "__beaver__": self,
            "log":        self.log_fn,
            "hive":       self.hive,
            "apix":       self.apix,
        }
        try:
            exec(compile(script["code"], f"<bvr:script:{script_id}>", "exec"), ns)
        except Exception as e:
            raise BeaverError(f"BVR020: Erreur exec script py id={script_id} : {e}")

        self._py_ns[script_id] = ns
        return ns

    def _call_py(self, script_id: int, fn_name: str, *args):
        ns = self._get_py_namespace(script_id)
        if fn_name not in ns or not callable(ns[fn_name]):
            raise BeaverError(f"BVR016: Fonction {fn_name} introuvable dans script id={script_id}")
        try:
            return ns[fn_name](*args)
        except SystemExit:
            raise
        except Exception as e:
            raise BeaverError(f"BVR020: Erreur lors de l'appel {fn_name}() : {e}")

    # ------------------------------------------------------------------
    # RCS script execution
    # ------------------------------------------------------------------

    def _call_rcs(self, script_id: int, fn_name: str, *args):
        """
        Execute fn_name label in RCS script script_id.
        args[0] is expected to be the raw args string if called from main entry,
        or positional values if called inter-script.
        """
        script = self.bvr["scripts"][script_id]

        # Build context
        # If args[0] is a string and it's the only arg, treat as raw args string
        if len(args) == 1 and isinstance(args[0], str):
            raw_args_str = args[0]
            log_fn = self.log_fn
            hive   = self.hive
            apix   = self.apix
        else:
            # Inter-script call: extract log/hive/apix from positional args if present
            raw_args_str = ""
            log_fn = self.log_fn
            hive   = self.hive
            apix   = self.apix
            # Look for injected callables in args
            pos_args = []
            for a in args:
                if callable(a) and a is self.log_fn:
                    log_fn = a
                elif hasattr(a, "get") and hasattr(a, "set"):
                    hive = a
                else:
                    pos_args.append(str(a))
            # Reconstruct a positional args string for $p:N access
            raw_args_str = " ".join(pos_args)

        context = {
            "log":        log_fn,
            "args":       raw_args_str,
            "hive":       hive,
            "apix":       apix,
            "__beaver__": self,
        }

        interpreter = RCS(script["code"], context)

        # If fn_name is "R_ECO3" or matches a label, call that label
        # else run from top
        if fn_name in interpreter.labels:
            return interpreter.call_label(fn_name)
        elif fn_name == "R_ECO3":
            # Run from top (legacy entry point)
            return interpreter.execute()
        else:
            raise BeaverError(f"BVR014: Label/fonction {fn_name} introuvable dans script RCS id={script_id}")


# ---------------------------------------------------------------------------
# .bvr builder
# ---------------------------------------------------------------------------

BVRSEP_LINE = "|BVRSEP|"


def build_bvr(
    scripts: list[tuple[str, str]],   # list of (lang, code_or_filepath)
    name: str,
    desc: str,
    version: str,
    help_str: str = "",
    manual: str = "",
    dependance: str = "",
    start: str = None,
    from_files: bool = False,
) -> str:
    """
    Build a .bvr source string from components.

    scripts     : list of (lang, code) pairs.  lang = "py" | "rcs"
                  If from_files=True, code is a file path and content is read.
    name        : module name
    desc        : short description
    version     : version string
    help_str    : short usage help
    manual      : long manual text
    dependance  : raw Dependance string
    start       : "id:fn" — defaults to "0:main" if not given
    from_files  : if True, read script content from file paths
    """
    if not scripts:
        raise BeaverError("BVR040: Aucun script fourni")

    if start is None:
        start = "0:main"

    lines = ["#BEAVER1"]
    lines.append(f'Name       = "{name}"')
    lines.append(f'Desc       = "{desc}"')
    lines.append(f'Version    = "{version}"')

    if help_str:
        lines.append(f'Help       = "{help_str}"')

    if manual:
        lines.append(f'Manual     = {BVRSEP_LINE}')
        # Escape any literal |BVRSEP| inside manual
        lines.append(manual.replace(BVRSEP_LINE, BVRSEP_ESC))
        lines.append(BVRSEP_LINE)

    if dependance:
        lines.append(f'Dependance = {dependance}')

    lines.append(f'Start      = "{start}"')
    lines.append("")

    for idx, (lang, code_or_path) in enumerate(scripts):
        if lang not in ("py", "rcs"):
            raise BeaverError(f"BVR007: lang inconnu : {lang}")

        if from_files:
            try:
                with open(code_or_path, "r", encoding="utf-8") as f:
                    code = f.read()
            except OSError as e:
                raise BeaverError(f"BVR040: Impossible de lire {code_or_path} : {e}")
        else:
            code = code_or_path

        # Detect version hint from file extension or default
        ver = "3.10" if lang == "py" else "1.2"

        lines.append(f'Script {BVRSEP_LINE}lang={lang}, version={ver}, id={idx}{BVRSEP_LINE}')
        # Escape BVRSEP inside code
        lines.append(code.replace(BVRSEP_LINE, BVRSEP_ESC))
        lines.append(BVRSEP_LINE)
        lines.append("")

    return "\n".join(lines)


def _detect_dependencies_py(code: str) -> list[str]:
    """Scan Python code for core.xxx imports."""
    deps = []
    for m in re.finditer(r'import\s+(core\.\w+)', code):
        deps.append(m.group(1))
    for m in re.finditer(r'from\s+(core)\s+import\s+(\w+)', code):
        deps.append(f"core.{m.group(2)}")
    return list(set(deps))


def _detect_dependencies_rcs(code: str) -> list[str]:
    """Scan RCS code for > module calls."""
    deps = []
    for m in re.finditer(r'^\s*>\s+(\w+)', code, re.MULTILINE):
        mod = m.group(1)
        # Exclude built-ins
        if mod not in ("echo",):
            deps.append(mod)
    return list(set(deps))


def auto_detect_dependencies(scripts: list[tuple[str, str]]) -> str:
    """
    Auto-detect dependencies from a list of (lang, code) pairs.
    Returns a raw Dependance string.
    """
    all_deps = set()
    for lang, code in scripts:
        if lang == "py":
            all_deps.update(_detect_dependencies_py(code))
        elif lang == "rcs":
            all_deps.update(_detect_dependencies_rcs(code))

    if not all_deps:
        return ""

    parts = [f'("{dep}", ("1.0",))' for dep in sorted(all_deps)]
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# beaver subcommands
# ---------------------------------------------------------------------------

def cmd_exe(bvr_path: str, args_str: str, log_fn=None, hive=None, apix=None):
    """
    beaver exe <file.bvr> [args]
    Execute a .bvr file without installing it.
    Returns (code, value).
    """
    log = log_fn or print
    try:
        bvr = parse_bvr_file(bvr_path)
    except FileNotFoundError:
        return (1, f"BVR040: Fichier introuvable : {bvr_path}")
    except BeaverError as e:
        return (1, str(e))

    instance = BeaverInstance(bvr, hive=hive, apix=apix, log_fn=log)
    return instance.execute(args=args_str, log_fn=log)


def cmd_build(
    script_paths: list[str],
    header_path: str = None,
    output_path: str = None,
    interactive: bool = True,
    log_fn=None,
) -> str:
    """
    beaver build <script1> [script2 ...] [header.bvrh]
    Assemble one or more scripts (+ optional .bvrh header) into a .bvr.

    script_paths : list of paths to .py or .rcs source files.
    header_path  : optional .bvrh path for metadata.
    output_path  : where to write the .bvr (None = auto from first script name).
    interactive  : if True and no header, prompt for metadata via input().
    Returns the output file path.
    """
    log = log_fn or print

    # Separate .bvrh files from script files
    script_sources = []
    detected_header = header_path

    for path in script_paths:
        if path.endswith(".bvrh"):
            if detected_header:
                raise BeaverError("BVR041: Plusieurs fichiers .bvrh fournis")
            detected_header = path
        elif path.endswith(".py"):
            script_sources.append(("py", path))
        elif path.endswith((".rcs", ".bvrs")):
            script_sources.append(("rcs", path))
        else:
            raise BeaverError(f"BVR040: Extension de fichier inconnue : {path}")

    if not script_sources:
        raise BeaverError("BVR040: Aucun fichier script (.py, .rcs, .bvrs) fourni")

    # Parse header if present
    meta = {
        "name": None,
        "desc": None,
        "version": None,
        "help": "",
        "manual": "",
        "dependance": "",
        "start": "0:main",
    }

    if detected_header:
        try:
            with open(detected_header, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError as e:
            raise BeaverError(f"BVR041: Impossible de lire le header : {e}")
        parsed = parse_bvr(raw + "\n# placeholder script\nScript |BVRSEP|lang=rcs, version=1.0, id=0|BVRSEP|\n|BVRSEP|\n")
        for k in ("name", "desc", "version", "help", "manual", "dependance", "start"):
            meta[k] = parsed.get(k, meta[k])
        # fix: parsed may set start even without scripts
    elif interactive:
        log("[beaver] Construction du module .bvr")
        meta["name"]    = input("[beaver] Nom       : ").strip()
        meta["desc"]    = input("[beaver] Desc      : ").strip()
        meta["version"] = input("[beaver] Version   : ").strip()
        meta["help"]    = input("[beaver] Help      : ").strip()
        start_input     = input("[beaver] Start     : (défaut 0:main) ").strip()
        meta["start"]   = start_input if start_input else "0:main"
        auto = input("[beaver] Calculer les dépendances automatiquement ? [Y/n] ").strip().lower()
        if auto in ("", "y", "yes", "o", "oui"):
            # Read scripts to detect deps
            script_codes = []
            for lang, path in script_sources:
                with open(path, "r", encoding="utf-8") as f:
                    script_codes.append((lang, f.read()))
            meta["dependance"] = auto_detect_dependencies(script_codes)
            if meta["dependance"]:
                log(f"[beaver] Dépendances détectées : {meta['dependance']}")
    else:
        raise BeaverError("BVR002: Métadonnées obligatoires manquantes et mode non-interactif")

    # Validate mandatory fields
    for field in ("name", "desc", "version"):
        if not meta[field]:
            raise BeaverError(f"BVR002: Champ obligatoire absent : {field}")

    # Build output
    bvr_content = build_bvr(
        scripts    = script_sources,
        name       = meta["name"],
        desc       = meta["desc"],
        version    = meta["version"],
        help_str   = meta["help"],
        manual     = meta["manual"],
        dependance = meta["dependance"],
        start      = meta["start"],
        from_files = True,
    )

    if output_path is None:
        first_script = os.path.splitext(os.path.basename(script_sources[0][1]))[0]
        output_path = f"{first_script}.bvr"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(bvr_content)

    log(f"[beaver] Fichier .bvr créé : {output_path}")
    return output_path


def cmd_install(bvr_path: str, hive, log_fn=None):
    """
    beaver install <file.bvr>
    Install a .bvr into HiveFS and register it with mycelium.
    """
    log = log_fn or print

    try:
        bvr = parse_bvr_file(bvr_path)
    except FileNotFoundError:
        return (1, f"BVR040: Fichier introuvable : {bvr_path}")
    except BeaverError as e:
        return (1, str(e))

    if hive is None:
        return (1, "BVR030: hive non disponible")

    name = bvr["name"]

    with open(bvr_path, "r", encoding="utf-8") as f:
        src = f.read()

    # Determine start script lang
    start_id_str, _ = bvr["start"].split(":", 1)
    start_id = int(start_id_str)
    start_lang = bvr["scripts"].get(start_id, {}).get("lang", "rcs")

    try:
        hive.set(f"§sys:beaver:app:{name}.src",     src)
        hive.set(f"§sys:beaver:app:{name}.name",    name)
        hive.set(f"§sys:beaver:app:{name}.desc",    bvr["desc"])
        hive.set(f"§sys:beaver:app:{name}.version", bvr["version"])
        hive.set(f"§sys:beaver:app:{name}.help",    bvr["help"])
        hive.set(f"§sys:beaver:app:{name}.lang",    start_lang)
        hive.set(f"§sys:beaver:app:{name}.start",   bvr["start"])
    except Exception as e:
        return (1, f"BVR030: Erreur d'écriture HiveFS : {e}")

    # Update global registry
    try:
        existing_raw = hive.get("§sys:beaver:available.all") or ""
        existing = [x for x in existing_raw.split("<RECO_SEP:=:>") if x]
        if name not in existing:
            existing.append(name)
        hive.set("§sys:beaver:available.all", "<RECO_SEP:=:>".join(existing))
    except Exception as e:
        return (1, f"BVR030: Erreur mise à jour du registre : {e}")

    # Register mycelium rule
    mycelium_rule = (
        f"{name} * = beaver exe-installed {name} * ||| "
        f"{name} /* = beaver exe-installed {name}"
    )
    try:
        hive.set(f"§sys:mycelium:{name}", mycelium_rule)
    except Exception as e:
        return (1, f"BVR031: Erreur enregistrement mycelium : {e}")

    log(f"[beaver] Module '{name}' v{bvr['version']} installé avec succès.")
    return (0, name)


def cmd_exe_installed(name: str, args_str: str, hive, log_fn=None, apix=None):
    """
    beaver exe-installed <name> [args]
    Internal: execute an installed module by name from HiveFS.
    """
    log = log_fn or print

    if hive is None:
        return (1, "BVR011: hive non disponible")

    src = hive.get(f"§sys:beaver:app:{name}.src")
    if src is None:
        return (1, f"BVR050: Module non installé : {name}")

    try:
        bvr = parse_bvr(src)
    except BeaverError as e:
        return (1, str(e))

    instance = BeaverInstance(bvr, hive=hive, apix=apix, log_fn=log)
    return instance.execute(args=args_str, log_fn=log)


def cmd_list(hive, log_fn=None):
    """
    beaver list
    List all installed beaver modules.
    """
    log = log_fn or print

    if hive is None:
        return (1, "BVR011: hive non disponible")

    raw = hive.get("§sys:beaver:available.all") or ""
    names = [n for n in raw.split("<RECO_SEP:=:>") if n]

    if not names:
        log("[beaver] Aucun module installé.")
        return (0, [])

    results = []
    for name in sorted(names):
        ver  = hive.get(f"§sys:beaver:app:{name}.version") or "?"
        desc = hive.get(f"§sys:beaver:app:{name}.desc")    or ""
        log(f"  {name:<20} v{ver:<10} {desc}")
        results.append((name, ver, desc))

    return (0, results)


def cmd_show(name: str, hive, log_fn=None):
    """
    beaver show <name>
    Display the full .bvr source of an installed module.
    """
    log = log_fn or print

    if hive is None:
        return (1, "BVR011: hive non disponible")

    src = hive.get(f"§sys:beaver:app:{name}.src")
    if src is None:
        return (1, f"BVR050: Module non installé : {name}")

    log(src)
    return (0, src)


def cmd_delete(name: str, hive, log_fn=None):
    """
    beaver delete <name>
    Uninstall a beaver module.
    """
    log = log_fn or print

    if hive is None:
        return (1, "BVR011: hive non disponible")

    src = hive.get(f"§sys:beaver:app:{name}.src")
    if src is None:
        return (1, f"BVR050: Module non installé : {name}")

    keys = ["src", "name", "desc", "version", "help", "lang", "start"]
    for k in keys:
        try:
            hive.delete(f"§sys:beaver:app:{name}.{k}")
        except Exception:
            pass

    # Remove from registry
    try:
        raw = hive.get("§sys:beaver:available.all") or ""
        names = [n for n in raw.split("<RECO_SEP:=:>") if n and n != name]
        hive.set("§sys:beaver:available.all", "<RECO_SEP:=:>".join(names))
    except Exception as e:
        return (1, f"BVR030: Erreur mise à jour du registre : {e}")

    # Remove mycelium rule
    try:
        hive.delete(f"§sys:mycelium:{name}")
    except Exception:
        pass

    log(f"[beaver] Module '{name}' désinstallé.")
    return (0, name)


def cmd_export(name: str, output_path: str = None, hive=None, log_fn=None):
    """
    beaver export <name> [output.bvr]
    Recreate the .bvr file from HiveFS.
    """
    log = log_fn or print

    if hive is None:
        return (1, "BVR011: hive non disponible")

    src = hive.get(f"§sys:beaver:app:{name}.src")
    if src is None:
        return (1, f"BVR050: Module non installé : {name}")

    if output_path is None:
        output_path = f"{name}.bvr"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(src)

    log(f"[beaver] Module '{name}' exporté vers {output_path}")
    return (0, output_path)


def cmd_status(hive, log_fn=None):
    """
    beaver status
    Display beaver version info and install stats.
    """
    log = log_fn or print

    log("beaver v1.0 · R-ECO3 v3.5.1b · Codename Ant")

    if hive is not None:
        raw = hive.get("§sys:beaver:available.all") or ""
        count = len([n for n in raw.split("<RECO_SEP:=:>") if n])
        log(f"Modules installés : {count}")

    return (0, None)


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def cmd_repl(hive=None, apix=None, log_fn=None):
    """
    beaver repl
    Interactive REPL to build and test beaver modules.
    """
    log = log_fn or print
    log("beaver REPL v1.0 — tapez 'quit' pour quitter, 'help' pour l'aide")

    current_bvr = None      # parsed bvr dict in progress
    current_src = None      # raw source in progress

    def _show_help():
        log("""Commandes disponibles :
  new                     → démarre un nouveau module
  edit <name>             → charge un module installé pour modification
  load <file.bvr>         → charge un fichier .bvr
  set <champ> <valeur>    → modifie un champ d'en-tête
  script add <lang>       → ajoute un bloc Script
  script edit <id>        → édite un bloc Script existant
  run [args]              → exécute le module en cours
  build                   → génère le .bvr dans le répertoire courant
  install                 → installe le module en cours
  status                  → affiche l'état du module en cours
  clear                   → efface le module en cours
  quit                    → quitte le REPL""")

    while True:
        try:
            raw = input("bvr> ").strip()
        except (EOFError, KeyboardInterrupt):
            log("\n[beaver] REPL terminé.")
            break

        if not raw or raw.startswith("#"):
            continue

        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "quit":
            log("[beaver] REPL terminé.")
            break

        elif cmd == "help":
            _show_help()

        elif cmd == "new":
            current_bvr = {
                "name": "", "desc": "", "version": "1.0",
                "help": "", "manual": "", "dependance": "",
                "start": "0:main", "scripts": {}
            }
            current_src = None
            log("[beaver] Nouveau module initialisé. Utilisez 'set' pour configurer.")

        elif cmd == "clear":
            current_bvr = None
            current_src = None
            log("[beaver] Module effacé.")

        elif cmd == "status":
            if current_bvr is None:
                log("[beaver] Aucun module en cours.")
            else:
                log(f"  Name    : {current_bvr.get('name', '(vide)')}")
                log(f"  Desc    : {current_bvr.get('desc', '(vide)')}")
                log(f"  Version : {current_bvr.get('version', '(vide)')}")
                log(f"  Start   : {current_bvr.get('start', '(vide)')}")
                log(f"  Scripts : {list(current_bvr.get('scripts', {}).keys())}")

        elif cmd == "load":
            path = rest.strip()
            try:
                current_bvr = parse_bvr_file(path)
                log(f"[beaver] Chargé : {path}")
            except Exception as e:
                log(f"[beaver] Erreur : {e}")

        elif cmd == "edit":
            name = rest.strip()
            if hive is None:
                log("[beaver] hive non disponible")
                continue
            src = hive.get(f"§sys:beaver:app:{name}.src")
            if src is None:
                log(f"[beaver] Module '{name}' non trouvé")
                continue
            try:
                current_bvr = parse_bvr(src)
                log(f"[beaver] Module '{name}' chargé pour modification")
            except Exception as e:
                log(f"[beaver] Erreur : {e}")

        elif cmd == "set":
            if current_bvr is None:
                log("[beaver] Aucun module en cours. Utilisez 'new' d'abord.")
                continue
            sub = rest.split(None, 1)
            if len(sub) < 2:
                log("[beaver] Usage : set <champ> <valeur>")
                continue
            field, val = sub[0].lower(), sub[1]
            if field in ("name", "desc", "version", "help", "start", "manual", "dependance"):
                current_bvr[field] = val.strip('"')
                log(f"[beaver] {field} = {current_bvr[field]}")
            else:
                log(f"[beaver] Champ inconnu : {field}")

        elif cmd == "script":
            if current_bvr is None:
                log("[beaver] Aucun module en cours. Utilisez 'new' d'abord.")
                continue
            sub = rest.split(None, 1)
            if not sub:
                log("[beaver] Usage : script add <lang> | script edit <id>")
                continue
            action = sub[0].lower()

            if action == "add":
                lang = sub[1].strip() if len(sub) > 1 else "rcs"
                if lang not in ("py", "rcs"):
                    log(f"[beaver] lang inconnu : {lang}")
                    continue
                new_id = max(current_bvr["scripts"].keys(), default=-1) + 1
                log(f"[beaver] Entrez le code du script id={new_id} (lang={lang}).")
                log("[beaver] Terminez avec une ligne contenant uniquement '---END---'")
                code_lines = []
                while True:
                    try:
                        cl = input()
                    except EOFError:
                        break
                    if cl.strip() == "---END---":
                        break
                    code_lines.append(cl)
                current_bvr["scripts"][new_id] = {
                    "lang": lang,
                    "version": "3.10" if lang == "py" else "1.2",
                    "code": "\n".join(code_lines),
                }
                log(f"[beaver] Script id={new_id} ajouté.")

            elif action == "edit":
                try:
                    sid = int(sub[1]) if len(sub) > 1 else -1
                except ValueError:
                    log("[beaver] Usage : script edit <id>")
                    continue
                if sid not in current_bvr["scripts"]:
                    log(f"[beaver] Script id={sid} introuvable")
                    continue
                lang = current_bvr["scripts"][sid]["lang"]
                log(f"[beaver] Entrez le nouveau code du script id={sid} (lang={lang}).")
                log("[beaver] Terminez avec une ligne contenant uniquement '---END---'")
                code_lines = []
                while True:
                    try:
                        cl = input()
                    except EOFError:
                        break
                    if cl.strip() == "---END---":
                        break
                    code_lines.append(cl)
                current_bvr["scripts"][sid]["code"] = "\n".join(code_lines)
                log(f"[beaver] Script id={sid} mis à jour.")
            else:
                log("[beaver] Usage : script add <lang> | script edit <id>")

        elif cmd == "run":
            if current_bvr is None:
                log("[beaver] Aucun module en cours.")
                continue
            args_str = rest.strip()
            instance = BeaverInstance(current_bvr, hive=hive, apix=apix, log_fn=log)
            code, val = instance.execute(args=args_str, log_fn=log)
            if code == 0:
                log(f"[beaver] Résultat : {val}")
            else:
                log(f"[beaver] Erreur ({code}) : {val}")

        elif cmd == "build":
            if current_bvr is None:
                log("[beaver] Aucun module en cours.")
                continue
            name = current_bvr.get("name", "module")
            scripts_list = [
                (s["lang"], s["code"])
                for s in current_bvr["scripts"].values()
            ]
            try:
                content = build_bvr(
                    scripts    = scripts_list,
                    name       = current_bvr["name"],
                    desc       = current_bvr["desc"],
                    version    = current_bvr["version"],
                    help_str   = current_bvr.get("help", ""),
                    manual     = current_bvr.get("manual", ""),
                    dependance = current_bvr.get("dependance", ""),
                    start      = current_bvr.get("start", "0:main"),
                    from_files = False,
                )
                out = f"{name}.bvr"
                with open(out, "w", encoding="utf-8") as f:
                    f.write(content)
                log(f"[beaver] Fichier généré : {out}")
            except BeaverError as e:
                log(f"[beaver] Erreur build : {e}")

        elif cmd == "install":
            if current_bvr is None:
                log("[beaver] Aucun module en cours.")
                continue
            if hive is None:
                log("[beaver] hive non disponible")
                continue
            name = current_bvr.get("name", "module")
            # Build to temp then install
            scripts_list = [
                (s["lang"], s["code"])
                for s in current_bvr["scripts"].values()
            ]
            try:
                content = build_bvr(
                    scripts    = scripts_list,
                    name       = current_bvr["name"],
                    desc       = current_bvr["desc"],
                    version    = current_bvr["version"],
                    help_str   = current_bvr.get("help", ""),
                    manual     = current_bvr.get("manual", ""),
                    dependance = current_bvr.get("dependance", ""),
                    start      = current_bvr.get("start", "0:main"),
                    from_files = False,
                )
                tmp = f"/tmp/__beaver_repl_{name}.bvr"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(content)
                code, val = cmd_install(tmp, hive, log_fn=log)
                if code != 0:
                    log(f"[beaver] Erreur installation : {val}")
            except BeaverError as e:
                log(f"[beaver] Erreur build : {e}")

        else:
            log(f"[beaver] Commande inconnue : {cmd}. Tapez 'help' pour l'aide.")

    return (0, None)


# ---------------------------------------------------------------------------
# R-ECO3 module interface
# ---------------------------------------------------------------------------

def R_ECO3(args, log_fn=print):
    """
    Main entry point for the beaver module in R-ECO3.
    Dispatches subcommands: exe, build, install, exe-installed,
    list, show, delete, export, repl, status.
    """
    parts = args.split() if isinstance(args, str) else []
    if not parts:
        log_fn("Usage: beaver <commande> [args]")
        log_fn("Commandes: exe, build, install, list, show, delete, export, repl, status")
        return 0

    subcmd = parts[0].lower()

    # These require hive/apix — injected by R-ECO3 caller
    hive = None
    apix = None

    if subcmd == "exe":
        if len(parts) < 2:
            log_fn("Usage: beaver exe <file.bvr> [args]")
            return 1
        bvr_path = parts[1]
        run_args = " ".join(parts[2:])
        code, val = cmd_exe(bvr_path, run_args, log_fn=log_fn, hive=hive, apix=apix)
        if code != 0:
            log_fn(str(val))
        return code

    elif subcmd == "build":
        if len(parts) < 2:
            log_fn("Usage: beaver build <script1> [script2 ...] [header.bvrh]")
            return 1
        script_paths = parts[1:]
        try:
            out = cmd_build(script_paths, log_fn=log_fn)
            log_fn(f"[beaver] Produit : {out}")
        except BeaverError as e:
            log_fn(str(e))
            return 1
        return 0

    elif subcmd == "install":
        if len(parts) < 2:
            log_fn("Usage: beaver install <file.bvr>")
            return 1
        code, val = cmd_install(parts[1], hive, log_fn=log_fn)
        if code != 0:
            log_fn(str(val))
        return code

    elif subcmd == "exe-installed":
        if len(parts) < 2:
            log_fn("Usage: beaver exe-installed <name> [args]")
            return 1
        name     = parts[1]
        run_args = " ".join(parts[2:])
        code, val = cmd_exe_installed(name, run_args, hive, log_fn=log_fn, apix=apix)
        if code != 0:
            log_fn(str(val))
        return code

    elif subcmd == "list":
        code, _ = cmd_list(hive, log_fn=log_fn)
        return code

    elif subcmd == "show":
        if len(parts) < 2:
            log_fn("Usage: beaver show <name>")
            return 1
        code, _ = cmd_show(parts[1], hive, log_fn=log_fn)
        return code

    elif subcmd == "delete":
        if len(parts) < 2:
            log_fn("Usage: beaver delete <name>")
            return 1
        code, _ = cmd_delete(parts[1], hive, log_fn=log_fn)
        return code

    elif subcmd == "export":
        name = parts[1] if len(parts) > 1 else None
        if name is None:
            log_fn("Usage: beaver export <name> [output.bvr]")
            return 1
        out = parts[2] if len(parts) > 2 else None
        code, _ = cmd_export(name, out, hive, log_fn=log_fn)
        return code

    elif subcmd == "repl":
        code, _ = cmd_repl(hive=hive, apix=apix, log_fn=log_fn)
        return code

    elif subcmd == "status":
        code, _ = cmd_status(hive, log_fn=log_fn)
        return code

    else:
        log_fn(f"BVR011: Sous-commande beaver inconnue : {subcmd}")
        return 1


def R_ECO3dep():
    """Returns the minimal dependencies required for module initialization."""
    return (
        ("3.5.1b",),
        (
            ("core.hive",  ("1.1",)),
            ("core.apix",  ("1.1",)),
            ("core.utils", ("1.1",)),
            ("core.trail", ()),
            ("spider",     ("1.8",)),
            ("mycelium",   ("1.1",)),
            ("banana",     ("1.1",)),
        )
    )


def R_ECO3inf():
    """Returns the metadata and help dictionary for RAVEN."""
    return {
        "name":        "beaver",
        "desc":        "Interpréteur et compilateur de modules .bvr pour R-ECO3",
        "help":        "beaver <commande> [args]",
        "version_mod": "1.0",
        "L2Module":    True,
        "manual": (
            "beaver — Module beaver v1.0\n"
            "============================\n"
            "\n"
            "SYNOPSIS\n"
            "    beaver <commande> [args]\n"
            "\n"
            "COMMANDES\n"
            "    exe <file.bvr> [args]          Exécute un .bvr sans l'installer\n"
            "    build <s1> [s2...] [h.bvrh]    Assemble des scripts en .bvr\n"
            "    install <file.bvr>             Installe un module dans HiveFS\n"
            "    exe-installed <name> [args]    Exécute un module installé (interne)\n"
            "    list                           Liste les modules installés\n"
            "    show <name>                    Affiche le source d'un module installé\n"
            "    delete <name>                  Désinstalle un module\n"
            "    export <name> [output.bvr]     Recrée le .bvr depuis HiveFS\n"
            "    repl                           Lance le REPL interactif\n"
            "    status                         Infos de version et statistiques\n"
            "\n"
            "DESCRIPTION\n"
            "    Beaver permet de créer des modules R-ECO3 sans écrire un module\n"
            "    Python complet. Les fichiers .bvr embarquent métadonnées et scripts\n"
            "    en lang=py ou lang=rcs (R-ECO Command Script).\n"
            "\n"
            "    La commande build accepte un nombre illimité de fichiers scripts\n"
            "    (.py, .rcs, .bvrs) et les assemble dans un seul .bvr avec des id\n"
            "    séquentiels (0, 1, 2, ...). Un fichier .bvrh optionnel fournit\n"
            "    les métadonnées.\n"
            "\n"
            "EXEMPLES\n"
            "    beaver exe greeter.bvr Alice\n"
            "    beaver build main.rcs utils.py header.bvrh\n"
            "    beaver build script1.py script2.py script3.rcs\n"
            "    beaver install greeter.bvr\n"
            "    beaver list\n"
            "    beaver show greeter\n"
            "    beaver delete greeter\n"
            "    beaver repl\n"
        ),
    }