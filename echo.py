def R_ECO3(inp):
    args = inp["args"]
    log_fn = inp["logfn"]
    log_fn(args)
    return 0

def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": []
    }
    
def R_ECO3inf():
    """Returns the metadata and help dictionary for RAVEN."""
    return {
        "name": "echo",
        "desc": "Echo — prints all provided arguments back to log output",
        "help": "Prints all provided positional arguments and key-value parameters back to the log output.",
        "version_mod": "2.1",
        "alias_rules": "test /* = echo test",
        "L2Module": True,
        "manual": (
            "echo — Echo module  v1.1\n"
            "========================\n"
            "\n"
            "SYNOPSIS\n"
            "    echo [args...]\n"
            "    echo [pos] [--key=value ...]\n"
            "\n"
            "DESCRIPTION\n"
            "    Prints all positional arguments and key-value pairs back to the log output.\n"
            "\n"
            "EXAMPLES\n"
            "    echo hello world\n"
            "    echo test --mode=debug --count=3\n"
        ),
    }
