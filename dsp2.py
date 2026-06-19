import core

def R_ECO3(inp):
    args = inp["args"]
    log_fn = inp["logfn"]
    pos, kv = core.utils.parse_command(args)
    command = pos[0]
    if command == "exe":
        core.apix.R_ECO3({"args": f"run banana err --msg='Unknown module : {args.split()[1]}'","logfn": log_fn})
    return 0

def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"banana": ["2.1"]},
        ]
    }
    
def R_ECO3inf():
    """Returns the metadata and help dictionary for RAVEN."""
    return {
        "name": "dsp2",
        "desc": "dsp2 — secondary dispatcher",
        "help": "",
        "version_mod": "2.1",
        "L2Module": True,
    }
