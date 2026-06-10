def R_ECO3(args, log_fn=print):
    log_fn(args)
    return 0
    
def R_ECO3dep():
    """Returns the minimal dependencies required for module initialization."""
    return (("3.5.1b",), ((),))

def R_ECO3inf():
    """Returns the metadata and help dictionary for RAVEN."""
    return {
        "name": "echo",
        "desc": "Echo — prints all provided arguments back to log output",
        "help": "Prints all provided positional arguments and key-value parameters back to the log output.",
        "version_mod": "1.1",
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
