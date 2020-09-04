
import threading
import os
import sys

from env import *
from globals import *

if sys.version_info[0] < 3:
    raise Exception("Python 3 or a more recent version is required.")

class ThreadManager:

    def __init__(self):
        self.procs = {}
        self.proclock = threading.Lock()
        self.event = threading.Event()
        self.clientgo = threading.Event()

    def release_client(self):
        self.clientgo.set()

    def client_wait(self):
        self.clientgo.wait()

    def complete(self):
        self.event.set()
        self.clientgo.set()

    def proc_wait(self, proc):
        with self.proclock:
          self.procs[proc.pid] = proc
        proc.wait()
        self.complete()

    def is_done(self):
        return self.event.is_set()

    def block_on_procs(self):
        self.event.wait()
        return poll_procs(*self.procs.values(), done=True)

    def kill(self):
        with self.proclock:
          procs = list(self.procs.values())[:]
        for p in procs:
            kill_proc(p)

    def __new_thread(self, target, args):
        try:
            target(*args)
        except Exception as e:
            LOGGER.exception("Thread threw exception: %s", str(e))
            self.complete()

    def new_thread(self, target, args):
        t = threading.Thread(
            target=ThreadManager.__new_thread, args=(self, target, args))
        t.daemon = True
        t.start()

    def monitor_in_thread(self, proc):
        self.new_thread(ThreadManager.proc_wait, (self, proc))

def ping_delay_threaded(ip, tm, nseconds=60):
    time.sleep(3)
    return True

def observe_app_thread(experiment, app):
    if app.get('system', experiment['system']) != "shenango":
        return

    tm = experiment['tm']
    ping_delay_threaded(app['ip'], tm)

    fullcmd = "taskset -c %d go run rstat.go {ip} 1 " % control_core()
    fullcmd += "| ts %s > rstat.{name}.log"

    if app['mac']:
        runcmd("sudo arp -s {ip} {mac} temp".format(**app))

    proc = launch(fullcmd.format(**app), cwd=experiment['name'])
    tm.proc_wait(proc)

def perf_mon(cfg, experiment, binary, monpid):
    # ensure not running global perf also
    assert "perf" not in experiment['hosts'][THISHOST]['utils']
    time.sleep(2)
    tm = experiment['tm']
    while not tm.is_done():
      try:
        pids_with_bname = runcmd("pgrep %s" %
                             os.path.basename(binary)).splitlines()
        break
      except:
        time.sleep(1)
    if tm.is_done(): return
    time.sleep(2)
    pids_with_bname = set(map(int, pids_with_bname))

    pids = get_pid_tree_set(monpid).intersection(pids_with_bname)
    assert len(pids) == 1

    events = cfg.get('perf-events') or [
        "cycles", "instructions",
        "topdown-total-slots", "topdown-fetch-bubbles",
        "topdown-slots-issued", "topdown-slots-retired",
        "topdown-recovery-bubbles",
        "L1-dcache-load-misses", "L1-icache-load-misses",
        "l2_rqsts.code_rd_miss",
        "LLC-load-misses", "LLC-loads",
    ]

    interval_ms = cfg.get('perf_interval_ms', 1000)

    cmd = "sudo {}perf stat -p {} -I {} -x\\; -e ".format(PERFDIR, pids.pop(), interval_ms)
    cmd += ",".join(events)
    cmd += " |& ts %s > {name}.perf.out".format(**cfg)

    proc = launch(cmd, cwd=experiment['name'])
    experiment['tm'].proc_wait(proc)


def launch_shenango_program(cfg, experiment):
    assert 'args' in cfg

    binary = cfg.get('binary') or binaries[cfg['app']]['shenango']

    if os.access(experiment['name'] + "/" + os.path.basename(binary.split()[0]), os.F_OK):
        binary = "./" + os.path.basename(binary)
    else:
        assert os.access(binary.split()[0], os.F_OK), binary.split()[0]

    gen_conf(
        "{}/{}.config".format(experiment['name'], cfg['name']), experiment, **cfg)

    args = cfg['args'].format(**cfg)
    envs = " ".join(cfg.get('env', []))
    strace = ""
    ts = ""

    fullcmd = "ulimit -S -c 0 && "
    do_sudo = cfg.get('sudo', False)
    for c in cfg.get('custom_conf', []):
      do_sudo |= "enable_directpath" in c
    if do_sudo:
        fullcmd += "exec sudo {envs}"
    else:
        fullcmd += "{envs} exec"

    prio = "nice -n -19" if do_sudo else ""
    if ts: fullcmd += " stdbuf -i0 -o0 -e0"
    fullcmd += " numactl -N {numa_node} -m {numa_memory} {prio} {strace} {bin} {name}.config {args} {ts} > {name}.out 2> {name}.err"

    if cfg.get('timestamp'):
        ts = "|& ts %s"
    if 'strace' in cfg:
        strace = "strace -e trace=!ioctl"
    numa_node = cfg.get('numa_node', 0)
    numa_memory = cfg.get('numa_memory', 0)

    fullcmd = fullcmd.format(envs=envs, bin=binary, name=cfg[
                             'name'], args=args, strace=strace, ts=ts, numa_memory=numa_memory, numa_node=numa_node, prio=prio)

    for cmd in cfg.get('before', []):
        FUNCTION_REGISTRY[cmd](cfg, experiment)

    for ip in cfg.get('ping_deps', []):
        ping_delay_threaded(ip, experiment['tm'])

    tm = experiment['tm']

    proc = launch(fullcmd, cwd=experiment['name'])
    tm.monitor_in_thread(proc)

    for cmd in cfg.get('after', []):
        FUNCTION_REGISTRY[cmd](cfg, experiment)


def launch_linux_program(cfg, experiment):
    assert 'args' in cfg
    assert 'nice' in cfg
    assert cfg['ip'] == get_linux_ip(THISHOST)

    system = cfg.get('system') or experiment['system']

    binary = cfg.get('binary', None) or binaries[cfg['app']][system]
    if os.access(experiment['name'] + "/" + os.path.basename(binary), os.F_OK):
        binary = "./" + os.path.basename(binary)
    else:
        assert os.access(binary.split()[0], os.F_OK), binary.split()[0]

    name = cfg['name']

    prio = ""
    if cfg['nice'] > 0:
        prio = "chrt --idle 0"
        #prio = "nice -n {}".format(cfg['nice'])

    args = cfg['args'].format(**cfg)

    numa_node = cfg.get('numa_node', 0)
    numa_memory = cfg.get('numa_memory', 0)
    core_list = cfg.get('corelimit', '')
    if core_list:
        core_list = "-C " + core_list

    envs = " ".join(cfg.get('env', []))

    strace = "strace" if cfg.get('strace') else ""
    sudo = "sudo" if cfg.get('sudo') else ""
    timestamp = "|& ts %s" if cfg.get('timestamp') else ""

    fullcmd = "{sudo} {envs} stdbuf -i0 -o0 -e0 numactl -N {numa_node} -m {numa_memory} {bind} {prio} {strace} {bin} {args} {timestamp} > {name}.out 2>&1"
    fullcmd = fullcmd.format(numa_node=numa_node, numa_memory=numa_memory, bind=core_list, bin=binary, envs=envs,
                             sudo=sudo, name=name, args=args, prio=prio, timestamp=timestamp, strace=strace)

    for cmd in cfg.get('before', []):
        FUNCTION_REGISTRY[cmd](cfg, experiment)

    for ip in cfg.get('ping_deps', []):
        ping_delay_threaded(ip, experiment['tm'])

    proc = launch(fullcmd, cwd=experiment['name'])
    experiment['tm'].monitor_in_thread(proc)

    if False and cfg['nice'] < 0:
        time.sleep(2)
        pid = proc.pid
        with open("/proc/{pid}/task/{pid}/children".format(pid=pid)) as f:
            for line in f:
                runcmd(
                    "sudo renice -n {} -p $(ls /proc/{}/task)".format(cfg['nice'], line.strip()))

    for cmd in cfg.get('after', []):
        FUNCTION_REGISTRY[cmd](cfg, experiment)
    tm = experiment['tm']
 
def release_clients(cfg, experiment):
    experiment['tm'].release_client()

register_fn('release_clients', release_clients)

def launch_apps(experiment):
    launcher = {
        'shenango': launch_shenango_program,
        'linux': launch_linux_program,
        'linux-floating': launch_linux_program,
        'linux-partitioned': launch_linux_program,
    }

    tm = experiment['tm']
    for cfg in experiment['hosts'][THISHOST]['apps']:
        system = cfg.get('system', experiment.get('system'))
        tm.new_thread(target=launcher[system],
                      args=(cfg, experiment))
