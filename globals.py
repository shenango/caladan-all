import logging
import random
import sys
import subprocess
import time

try:
  from termcolor import colored
except:
  def colored(txt, color): return txt

FUNCTION_REGISTRY = {}

def register_fn(name, fn):
  global FUNCTION_REGISTRY
  FUNCTION_REGISTRY[name] = fn

KILL_PROCS = [
    "iokerneld", "cstate", "memcached", "x264",
    "swaptions", "mpstat", "rstat", "go", "stress",
    "storage_server", "silo"
]

LOGGER = logging.getLogger('experiment')
logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.INFO)

def _reset_log():
  import sys
  for handler in LOGGER.handlers[:]: LOGGER.removeHandler(handler)
  sh = logging.StreamHandler(sys.stdout)
  LOGGER.addHandler(sh)

def INITLOGGING(exp):
  _reset_log()
  _hostname = subprocess.check_output("hostname -s", shell=True).strip().decode('utf-8')
  fh = logging.FileHandler('{}/pylog.{}.log'.format(exp['name'], _hostname))
  fh.setLevel(logging.DEBUG)
  LOGGER.addHandler(fh)

NETPFX = "0.0.0"
EXP_BASE = "./"
SHELL = "/bin/bash"


def mask_to_list(mask):
    i = 0
    l = []
    while mask:
        if mask & 1: l.append(i)
        mask >>= 1
        i += 1
    return l

def list_to_mask(l):
    i = 0
    for w in l:
        i |= 1 << w
    return i

def core_list(r):
    return ",".join(map(str, r))

def set_pfx(netpfx):
    global NETPFX
    NETPFX = netpfx


def IP(node):
    assert node > 0 and node < 255
    return "{}.{}".format(NETPFX, node)


def gen_random_mac():
    return ":".join(["02"] + ["%02x" % random.randint(0, 255) for i in range(5)])


def _runcmd(cmdstr, outp, suppress=False, **kwargs):
    kwargs['executable'] = kwargs.get("executable", SHELL)
    kwargs['cwd'] = kwargs.get('cwd', EXP_BASE)
    pfn = LOGGER.debug if True or suppress else LOGGER.info
    if outp:
        pfn("running {%s}: " % cmdstr)
        res = subprocess.check_output(cmdstr, shell=True, **kwargs)
#        pfn("%s\n" % res.strip())
        return res
    else:
        p = subprocess.Popen(cmdstr, shell=True,
                             stdin=subprocess.PIPE, **kwargs)
        LOGGER.info("[%04d]: launched {%s}" % (p.pid, cmdstr))
        return p

def launch(*args, **kwargs):
    assert 'outp' not in kwargs
    assert len(args) == 1
    return _runcmd(args[0], False, **kwargs)

def runcmd(*args, **kwargs):
    assert 'outp' not in kwargs
    assert len(args) == 1
    return _runcmd(args[0], True, **kwargs)

def launch_para(cmd, inputs, die_on_failure=True, **kwargs):
    fail = "--halt now,success=1" if die_on_failure else ""
    cmd = "PARALLEL_SHELL={} parallel -j {} {} \"{}\" ::: {}".format(SHELL, len(inputs), fail, cmd, " ".join(inputs))
    return launch(cmd, **kwargs)

def runpara(cmd, inputs, die_on_failure=False, **kwargs):
    fail = "--halt now,success=1" if die_on_failure else ""
    cmd = "PARALLEL_SHELL={} parallel -j {} {} \"{}\" ::: {}".format(SHELL, len(inputs), fail, cmd, " ".join(inputs))
    return runcmd(cmd, **kwargs)

def runremote(cmd, hosts, **kwargs):
    return runpara("ssh -t -t {{}} '{cmd}'".format(cmd=cmd), hosts, **kwargs)

def launchremote(cmd, hosts, **kwargs):
    return launch_para("ssh -t -t {{}} '{cmd}'".format(cmd=cmd), hosts, **kwargs)


def poll_procs(*l, **kwargs):
    assert len(l) > 0
    done = kwargs.get('done', False)
    ret = None
    while True:
        for p in l:
            if p.poll() != None:
                txt = "[%04d] is done, ret = %d" % (p.pid, p.returncode)
                ret = p.returncode
                if p.returncode != 0:
                    LOGGER.error(txt)
                else:
                    LOGGER.info(txt)
                done = True
        if not done: time.sleep(2)
        else: break
    return ret

def except_none(func):
    def e(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except:
            return None
    return e

@except_none
def kill_single(pid):
    runcmd("sudo kill -SIGINT %d 2> /dev/null" % pid, suppress=True)

def get_kids_list(pid):
    lns = runcmd("ps -o pid --ppid %d --noheaders || true" % pid, suppress=True).splitlines()
    if lns: lns = map(int, lns)
    return lns

def kill_pid_and_kids(pid):
    kids = get_kids_list(pid)
    if kids:
        for i in kids:
            kill_pid_and_kids(i)
    kill_single(pid)

def get_pid_tree_set(pid):
    kids = get_kids_list(pid)
    desc = set([pid])
    if kids:
        desc |= set(kids)
        for i in kids:
            desc |= get_pid_tree_set(i)
    return desc

def kill_proc(proc):
    kill_pid_and_kids(proc.pid)

# mark script changes that need to be reverted
def expires(*args):
    from datetime import datetime
    assert datetime.now() < datetime(*args)

