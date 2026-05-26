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
        "L2Module": True,
        "manual": (
            "echo [args]\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  echo [pos] [--key=value ...]\n"
            "    Prints all positional arguments and key-value pairs back to the log output.\n"
        )
    }
