import sys
import signal
import os
import subprocess
import time
import json
import atexit
import random
from pprint import pprint
from datetime import datetime
from collections import defaultdict

from env import *
from proclaunch import *
from globals import *

EXPERIMENT_DIR = "/tmp"

## experiment mutex ##
from fcntl import flock, LOCK_EX, LOCK_NB
os.system("sudo touch /tmp/experiment_lock; sudo chmod 666 /tmp/experiment_lock")
fd = open("/tmp/experiment_lock", "w")
flock(fd.fileno(), LOCK_EX | LOCK_NB)

## disable cron ##
cron_orig = os.system("sudo systemctl status cron > /dev/null 2>&1")
if cron_orig == 0:
    subprocess.check_output("sudo systemctl stop cron", shell=True)
    atexit.register(lambda: os.system("sudo systemctl start cron"))

atexit.register(lambda: sys.stdout.flush())
atexit.register(lambda: exitfn())

NEXT_CLIENT_ASSIGN = 0
# Requires password-less sudo and ssh
# TODO: clone/compile binaries? more sanity checks
# ts requires moreutils to be installed


################# Experiment Building Blocks #########################


def new_experiment(system, **kwargs):
    from os import path
    from glob import glob
    x = {
        'name': "run.{}".format(datetime.now().strftime('%Y%m%d%H%M%S')),
        'system': system,
        'hosts': {},
        'client_files': glob(path.split(path.realpath(__file__))[0] + "/*.py*"),
        'nextip': 100,
        'nextport': 5000 + random.randint(0, 255),
    }
    if kwargs.get('group_tag'):
        x['group_tag'] = kwargs['group_tag']
    if kwargs.get('name'):
        x['name'] += kwargs['name']
    if OBSERVER:
        x['observer'] = OBSERVER

    # send the binaries
    x['client_files'].append(binaries['iokerneld']['ht'])
    x['client_files'].append(CLIENT_BIN)

    return x

def enable_directpath(app, dp_arg="1"):
    app['custom_conf'] = app.get('custom_conf', []) + ['enable_directpath ' + dp_arg]

def start_mpstat(experiment):
    proc = launch("taskset -c {control} mpstat 1 -N ALL 2>&1 | taskset -c {control} ts %s > mpstat.{host}.log".format(
        control=control_core(), host=THISHOST), cwd=experiment['name'])
    return proc


def launch_util(experiment, name):
    fn = {
        'mpstat': start_mpstat,
     }.get(name)
    if not fn:
        fn = FUNCTION_REGISTRY.get(name)
    assert fn
    proc = fn(experiment)
    experiment['tm'].monitor_in_thread(proc)

def set_scheduler(scheduler, experiment, host=None, options=None):
    experiment['hosts'][host or THISHOST]['iokernel']['scheduler'] = scheduler
    if options: experiment['hosts'][host or THISHOST]['iokernel']['options'] = " ".join(options)

def add_host_to_exp(experiment, host):
    experiment['hosts'][host] = {
        'apps': [],
        'utils': [],
        'iokernel': {
    #        'binary': "./iokerneld",
            'scheduler': 'simple',
            'corelimit': core_list(MACHINES[host]['node0_cores']),
        },
        'linux': {}
    }


def add_util(experiment, name, host):
    if not host in experiment['hosts']:
        add_host_to_exp(experiment, host)
    assert not name in experiment['hosts'][host]['utils']
    experiment['hosts'][host]['utils'].append(name)


def add_app(experiment, app, host=THISHOST, **kwargs):
    if not host in experiment['hosts']:
        add_host_to_exp(experiment, host)
    app['host'] = host
    app['before'] = app.get('before', [])
    app['after'] = app.get('after', [])
    app['custom_conf'] = app.get('custom_conf', [])
    # enforce naming rules
    existing_apps = set(a['name'] for h in experiment['hosts']
                        for a in experiment['hosts'][h]['apps'])
    assert 'name' in app and app['name'] not in existing_apps
    experiment['hosts'][host]['apps'].append(app)


def alloc_ip(experiment, is_shenango_client=False, **kwargs):
    system = kwargs.get('system', experiment['system'])
    if system == "shenango" or is_shenango_client:
        ip = IP(experiment['nextip'])
        experiment['nextip'] += 1
        return ip

    return get_linux_ip(kwargs.get('host', kwargs.get('host', THISHOST)))


def alloc_port(experiment):
    port = experiment['nextport']
    experiment['nextport'] += 1
    return port


def new_memcached_server(threads, experiment, **kwargs):
    x = {
        'name': kwargs.get('name', "memcached"),
        'ip': alloc_ip(experiment),
        'port': alloc_port(experiment),
        'threads': threads,
        'guaranteed': threads,
        'spin': 0,
        'app': 'memcached',
        'nice': -20,
        'meml': 32000,
        'hashpower': 25,  # Note: NSDI 1.0 used 28
        'mac': gen_random_mac(),
        'protocol': 'memcached',
        'transport': kwargs.get('transport', "tcp"),
    }

    args = "-U {port} -p {port} -c 32768 -m {meml} -b 32768"
    args += " -o hashpower={hashpower}"

    args += {
        'linux': ",no_hashexpand,lru_crawler,lru_maintainer,idle_timeout=0",
        'shenango': ",no_hashexpand,lru_crawler,lru_maintainer,idle_timeout=0,slab_reassign",
    }.get(experiment['system'])

    x['args'] = "-t {threads} " + args

    add_app(experiment, x, **kwargs)

    return x

def new_swaptions_inst(threads, experiment, **kwargs):
    x = {
        'name': kwargs.get('name', "swaptions"),
        'ip': alloc_ip(experiment, **kwargs),
        'port': None,
        'mac': gen_random_mac(),
        'threads': threads,
        'guaranteed': 0,
        'spin': 0,
        'app': 'swaptions',
        'nice': 20,
        'simulations': 40000,
        'nswaptions': threads,
        'args': "-ns {nswaptions} -sm {simulations} -nt {threads}",
        'timestamp': False,
    }
    x.update(kwargs)
    add_app(experiment, x, **kwargs)
    return x


def new_measurement_instances(count, server_handle, mpps, experiment, mean=842, nconns=300, **kwargs):
    global NEXT_CLIENT_ASSIGN

    all_instances = []
    client_list = kwargs.get('client_list', CLIENT_SET)
    for i in range(count):
        client = client_list[(NEXT_CLIENT_ASSIGN + i) % len(client_list)]
        has_dp = get_nic(client).get('driver') in ['mlx5']
        x = {
            'custom_conf': ['enable_directpath 1'] if has_dp else [],
            'system': 'shenango',
            'ip': alloc_ip(experiment, is_shenango_client=True),
            'port': None,
            'mac': gen_random_mac(),
            'host': client,
            'name': "{}-{}.{}".format(i, client, server_handle['name']),
            'ping_deps': [server_handle['ip']],
            'app_name': server_handle['name'],
            'binary': "./synthetic --config",
            'app': 'synthetic',
            'serverip': server_handle['ip'],
            'serverport': server_handle['port'],
            'output': kwargs.get('output', "buckets"),
            'mpps': float(mpps) / count,
            'protocol': server_handle['protocol'],
            'transport': server_handle['transport'],
            'distribution': kwargs.get('distribution', "zero"),
            'mean': mean,
            'client_threads': nconns // count,
            'start_mpps': float(kwargs.get('start_mpps', 0)) / count,
            'warmup': '',
            'args': "{serverip}:{serverport} {warmup} --output={output} --protocol {protocol} --mode runtime-client --threads {client_threads} --runtime {runtime} --barrier-peers {npeers} --barrier-leader {leader}  --mean={mean} --distribution={distribution} --mpps={mpps} --samples={samples} --transport {transport} --start_mpps {start_mpps}"
        }
        if kwargs.get('rampup', None) is not None:
            x['args'] += " --rampup={rampup}"
            x['rampup'] = kwargs.get('rampup')
        add_app(experiment, x, host=client)
        all_instances.append(x)
    NEXT_CLIENT_ASSIGN += count
    return all_instances


def sleep_5(cfg, experiment):
    runcmd("sleep 5")


def finalize_measurement_cohort(cohort, experiment, samples, runtime):
    by_host = defaultdict(list)
    for c in cohort:
        by_host[c['host']].append(c)

    oobip = None
    for i, cfg in enumerate(cohort):
        host = cfg['host']
        threads = (len(MACHINES[host]['node0_cores']) -
                   2) // len(by_host[host]) & ~0x1
        # if cfg['host'] in ["zig", "zag"]:
        #     cfg['threads'] = 16 #16
        # else:
        cfg['threads'] = cfg.get('threads', threads)
        cfg['guaranteed'] = cfg.get('guaranteed', cfg['threads'])
        cfg['spin'] = cfg.get('spin', cfg['threads'])
        cfg['runtime'] = runtime
        cfg['npeers'] = len(cohort)
        cfg['samples'] = int(samples)
        if i == 0:
            oobip = MACHINES[host]['oob_ip']
            cfg['leader'] = host
        else:
            cfg['leader'] = oobip
            cfg['ping_deps'].append(cohort[0]['ip'])
            cfg['before'] = cfg.get('before', []) + ['sleep_5']

########################## EXPERIMENTS ###############################

def exitfn():
    global KILL_PROCS
    for key in binaries:
        for sys in binaries[key]:
            bname = os.path.basename(binaries[key][sys].split()[0])
            if bname not in KILL_PROCS:
                KILL_PROCS.append(bname)
    for j in KILL_PROCS:
        cmd = "sudo pkill " + j
        os.system(cmd)
    for j in KILL_PROCS:
        cmd = "sudo pkill -9 " + j
        os.system(cmd)

    os.system("sudo pkill -2 perl")

    runcmd("sudo ip -s -s neigh flush all")


def mask(core):
    s = []
    m = 1 << core
    while m:
        s.append("%x" % (m % (2**32)))
        m >>= 32
    return ",".join(reversed(s))

def steer_mlx_irqs():
    IRQS = check_output("cat /proc/interrupts | egrep 'mlx4|mlx5' | awk '{print $1}' | sed 's/://'", shell=True).decode().strip().splitlines()
    cores = list(range(0, 48, 2)) # todo fixme
    for i, irq in enumerate(IRQS):
        m = mask(cores[i % len(cores)])
        check_call("echo {} > /proc/irq/{}/smp_affinity".format(m, irq), shell=True)

def shenango_latency_tuning():
    LOGGER.info("Tuning machine latency settings")
    runcmd("sudo sysctl vm.stat_interval=500")
    runcmd("sudo sysctl -w kernel.watchdog=0")

    control_core_mask = list_to_mask([control_core()])
    managed_cpus = set(MACHINES[THISHOST]['node0_cores'])

    # migrate relevant processes
    proc = os.listdir('/proc/')
    for p in proc:
        if not os.access("/proc/{}/task".format(p), os.F_OK):
            continue
        if not p.isdigit():
            continue

        cur_mask = runcmd("taskset -p {}".format(p), suppress=True
                          ).decode().split(": ")[-1].strip()
        cur_mask = set(mask_to_list(int(cur_mask, 16)))
        if not (cur_mask & managed_cpus):
            continue

        # taskset [options] -p [mask] pid
        runcmd("sudo taskset -p {} {} > /dev/null 2>&1 || true".format(control_core_mask, p), suppress=True)

    # migrate irqs
    irqs = os.listdir('/proc/irq/')
    for i in irqs:
        if i == "0":
            continue
        runcmd("echo {} | sudo tee /proc/irq/{}/smp_affinity > /dev/null 2>&1 || true".format(control_core_mask, i), suppress=True)

    runcmd("echo {} | sudo tee /sys/bus/workqueue/devices/writeback/cpumask > /dev/null 2>&1".format(control_core_mask), suppress=True)


def switch_to_linux(exp):
    # assert is_server()
    print("switch to linux")

    if os.system('lspci | grep -q Optane') == 0:
        runcmd("sudo {}/spdk/scripts/setup.sh reset".format(SDIR))

    nic = list(MACHINES[THISHOST]['nics'].keys())[0]
    ip = MACHINES[THISHOST]['nics'][nic]['ip']

    runcmd("sudo ifdown {} || true".format(nic))
    runcmd("sudo ifup {} || true".format(nic))

    runcmd("sudo {}/scripts/setup_machine.sh || true".format(SDIR))
    runcmd("sudo pqos -R l3cdp-any || true")

    this_host_apps = exp['hosts'][THISHOST]['apps']
    has_udp = any(map(lambda a: a.get('transport') == "udp", this_host_apps))

    if MACHINES[THISHOST]['nics'][nic]['driver'] == "mlx5":
        if has_udp:
            print("WARNING! need to enable UDP RSS!")
        for setting in ["adaptive-rx off", "adaptive-tx off",
                        "rx-usecs 0", "rx-frames 0", "tx-usecs 0",
                        "tx-frames 0"]:
            runcmd("sudo ethtool -C {} {} || true".format(nic, setting))
    else:
        pass
    """
    runcmd("sudo {}/dpdk/usertools/dpdk-devbind.py -b none {}".format(SDIR, NIC_PCI))
    runcmd("sudo modprobe ixgbe")
    runcmd("sudo {}/dpdk/usertools/dpdk-devbind.py -b ixgbe {}".format(SDIR, NIC_PCI))
    """
    runcmd("sudo ethtool -N {} rx-flow-hash udp4 sdfn || true".format(nic))

    cfg = exp['hosts'][THISHOST].get('linux')
    if cfg:
        irq_affinities = cfg.get('irqs', 'local')
    else:
        irq_affinities = 'local'
    if MACHINES[THISHOST]['nics'][nic]['driver'] == "mlx5":
        assert THISHOST in ["zag", "zig"]
        steer_mlx_irqs()
    else:
        runcmd("sudo {}/scripts/set_irq_affinity {} {}".format(SDIR,
                                                           irq_affinities, nic))

    runcmd("sudo ip addr flush {} || true".format(nic))
    runcmd("sudo ip addr add {}/24 dev {}".format(ip, nic))
    runcmd("sudo sysctl net.ipv4.tcp_syncookies=1")
    return


def switch_to_shenango(exp):

    if os.system('lspci | grep -q Optane') == 0:
        runcmd("sudo {}/spdk/scripts/setup.sh".format(SDIR))

    if not os.access("{}/ksched/build/ksched.ko".format(SDIR), os.F_OK):
        runcmd("make", cwd="{}/ksched".format(SDIR))


    runcmd("sudo find /dev/hugepages/ -type f -delete")
    runcmd("sudo {}/scripts/setup_machine.sh || true".format(SDIR))

    hugepages = exp['hosts'][THISHOST].get('hugepages')
    if hugepages is not None:
        runcmd("echo {} | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages".format(
            hugepages))
        assert int(runcmd("cat /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages").strip()) == hugepages
    runcmd("echo 0 | sudo tee /sys/devices/system/node/node1/hugepages/hugepages-2048kB/nr_hugepages || true")

    if False:
        runcmd("sudo ifdown {} || true".format(NIC_IFNAME))
        runcmd("sudo modprobe uio")
        runcmd(
            "(lsmod | grep -q igb_uio) || sudo insmod {}/dpdk/build/kmod/igb_uio.ko".format(SDIR))
        runcmd(
            "sudo {}/dpdk/usertools/dpdk-devbind.py -b igb_uio {}".format(SDIR, NIC_PCI))

    shenango_latency_tuning()

############################# APPLICATIONS ###########################

# Launching configuration spec


def start_iokerneld(experiment):
    switch_to_shenango(experiment)
    cfg = experiment['hosts'][THISHOST].get('iokernel', {})
    scheduler = cfg.get('scheduler', 'simple')
    cores_setting = cfg.get('noht', cfg.get('corelimit', ''))
    binary = cfg.get('binary', binaries['iokerneld']['ht'])
    options = cfg.get('options', '')
    proc = launch("sudo {} {} {} {} 2>&1 | ts %s > iokernel.{}.log".format(
        binary, scheduler, cores_setting, options, THISHOST),
        cwd=experiment['name'])
    for i in range(10):
        if os.system("grep -q 'running dataplane' {}/iokernel.{}.log".format(experiment['name'], THISHOST)) == 0:
            break
        time.sleep(1)
        proc.poll()
        if proc.returncode is not None:
            break

    proc.poll()
    assert proc.returncode is None
    experiment['tm'].monitor_in_thread(proc)


def go_host(experiment):

    experiment['tm'] = ThreadManager()

    if experiment.get('observer') == THISHOST:
        assert not experiment['hosts'].get(THISHOST, {}).get('apps')
        poll_procs(*go_observer(experiment))
        return
    # Any given host should be entirely LINUX or SHENANGO
    apps = experiment['hosts'][THISHOST]['apps']
    systems = set(a.get('system', experiment['system']) for a in apps)
    # assert all(a.get('system', system) == system for a in apps)
    systems.add(experiment['system'])

    if "shenango" in systems:
        start_iokerneld(experiment)
    else:  # if "linux" in systems or "linux-floating" in systems:
        switch_to_linux(experiment)

    for util in experiment['hosts'][THISHOST]['utils']:
        launch_util(experiment, util)

    launch_apps(experiment)



def observe_app(experiment, app, pin_core=False):
    if app.get('system', experiment['system']) != "shenango":
        return

    fullcmd = "while ! ping -c 1 {ip} > /dev/null; do sleep 1; done; "
    if pin_core:
        fullcmd += "taskset -c %d " % control_core()
    fullcmd += "go run rstat.go {ip} 1 "
    fullcmd += "| ts %s > rstat.{name}.log"

    if app['mac']:
        runcmd("sudo arp -s {ip} {mac} temp".format(**app))

    return launch(fullcmd.format(**app), cwd=experiment['name'])


def go_observer(experiment):
    observer_nic = list(MACHINES[experiment['observer']]['nics'].keys())[0]
    runcmd("sudo ip addr add {}/24 dev {} || true".format(OBSERVER_IP, observer_nic))

    sleep_5(None, None)

    procs = []
    for host in experiment['hosts']:
        for app in experiment['hosts'][host]['apps']:
            syst = app.get('system') or experiment.get('system')
            if syst != "shenango":
                continue
            if "runtime-client" in app['args']:
                continue
            procs.append(observe_app(experiment, app))

    sys.stdout.write("monitoring %d procs" % len(procs))
    sys.stdout.flush()

    return procs

def verify_dates(host_list):
    ip_list = [MACHINES[h]['oob_ip'] for h in host_list]
    for i in range(3):  # try a few extra times
        while True:
            dates = set(runremote("date +%s", ip_list).splitlines())
            if dates:
                break
            else:
                print("retrying verify dates")
        if len(dates) == 1:
            return
        # Not more than one second off
        if len(dates) == 2:
            d1 = int(dates.pop())
            d2 = int(dates.pop())
            if (d1 - d2)**2 == 1:
                return
        time.sleep(1)
    assert False


def setup_experiment(experiment, all_hosts):

    verify_dates(all_hosts)

    os.makedirs(experiment['name'])

    runcmd("cp {} {}/".format(__file__, experiment['name']))
    conf_fn = experiment['name'] + "/config.json"
    with open(conf_fn, "w") as f:
        f.write(json.dumps(experiment))

    runcmd("(cd {}; git status; git log | head; git diff) > {}/gitstatus.$(hostname -s).log".format(SDIR,
                                                                                                    experiment['name']))
    if not all_hosts:
        return
    runremote("mkdir -p /{}/{}".format(
        EXPERIMENT_DIR, experiment['name']), all_hosts)
    files = " ".join(experiment['client_files'] + [conf_fn, RSTAT])

    runpara("scp {binary} {{}}:{topdir}/{expname}/".format(binary=files,
                                                           topdir=EXPERIMENT_DIR, expname=experiment['name']), all_hosts)


def collect_clients(experiment, remotes):
    if not remotes:
        return

    for ext in ["log", "out", "err", "data", "config"]:
        runpara(
            "scp -B {{}}:/{dir}/{exp}/*.{ext} {exp}/ || true".format(dir=EXPERIMENT_DIR, exp=experiment['name'], ext=ext), remotes)
    if True:
        runremote(
            "rm -rf /{}/{}".format(EXPERIMENT_DIR, experiment['name']), remotes)


def execute_experiment(experiment):

    for cmd in experiment.get('before', []):
        FUNCTION_REGISTRY[cmd](experiment)

    remotes = list(set(experiment['hosts'].keys()) - set([THISHOST]))

    if experiment.get('observer') and experiment['observer'] not in remotes:
        remotes.append(experiment['observer'])

    all_hosts = remotes + [THISHOST]
    setup_experiment(experiment, all_hosts)

    cwd = os.getcwd()
    os.chdir(EXPERIMENT_DIR)
    INITLOGGING(experiment)

    go_host(experiment)

    time.sleep(1)

    if experiment.get('manual_client_release'):
      experiment['tm'].client_wait()

    try:
        p = None
        client_cmd = "ulimit -S -c unlimited && python3 {topdir}/{dir}/experiment.py client {topdir}/{dir} > {topdir}/{dir}/py.{{}}.log 2>&1".format(
            topdir=EXPERIMENT_DIR, dir=experiment['name'], script=os.path.basename(__file__))
        if remotes:
            p = launchremote(client_cmd, remotes, die_on_failure=True)
            experiment['tm'].monitor_in_thread(p)
        ret = experiment['tm'].block_on_procs()
        try:
          if p:
              p.wait(30)
        except:
          pass
        #if ret != 0:
        #   raise Exception('proc exit code', ret)
    finally:
        os.chdir(cwd)

        while os.system("pgrep gdb") == 0: time.sleep(2)


        experiment['tm'].kill()
        time.sleep(2)
        try:
            collect_clients(experiment, all_hosts)
        except:
            pass
        experiment['tm'].kill()
        # for p in procs:
        #     kill_proc(p)
        #     del p
        exitfn()

    return experiment


def rep_external_partial(fn, start_mpps, mpps, samples, *args, **kwargs):
    group_tag = None
    intv = float(mpps - start_mpps) / float(samples)
    for i in range(1, samples + 1):
        mpps_local = start_mpps + intv * float(i)
        xp = fn(*args, mpps=mpps_local, samples=1, **kwargs)
        if not xp: continue
        if not group_tag:
            group_tag = xp['name']
        xp['group_tag'] = group_tag
        xp['name'] = '{}/{}mpps'.format(group_tag, mpps_local)
        execute_experiment(xp)

# runs one experiment per sample-point.
def rep_external(fn, mpps, samples, *args, **kwargs):
    rep_external_partial(fn, 0, mpps, samples, *args, **kwargs)

def release_clients(cfg, experiment):
    experiment['tm'].release_client()

register_fn('sleep_5', sleep_5)
register_fn('release_clients', release_clients)

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] == "server":
        pass

    elif sys.argv[1] == "client":
        assert len(sys.argv) == 3
        with open(sys.argv[2] + "/config.json") as f:
            experiment = json.loads(f.read())
        cwd = os.getcwd()
        os.chdir(EXPERIMENT_DIR)
        INITLOGGING(experiment)
        go_host(experiment)
        experiment['tm'].block_on_procs()
        experiment['tm'].kill()
    # elif sys.argv[1] == "observer":
    #     assert len(sys.argv) == 3
    #     go_observer(sys.argv[2])
    else:
        assert False, 'bad arg'
