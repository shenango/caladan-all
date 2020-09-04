from os import path
from subprocess import check_output
from globals import *

THISHOST = check_output("hostname -s", shell=True).strip().decode('utf-8')
SCRIPT_DIR = path.split(path.realpath(__file__))[0]

from base_dir import BASE_DIR
SDIR = "{}/shenango".format(BASE_DIR)
ZDIR = "{}/zygos-bench/".format(BASE_DIR)
CLIENT_BIN = "{}/apps/synthetic/target/release/synthetic".format(SDIR)

RSTAT = SDIR + "/scripts/rstat.go"
STORAGE_HOST = "zig"

NETPFX = "10.11.1"
set_pfx(NETPFX)
NETMASK = "255.255.255.0"
GATEWAY = IP(1)
OBSERVER = None

CLIENT_SET = ["pd10"]

MACHINES = {}
MACHINES["zag"] = {
    'nics': {
        'enp6s0f0': {
            'driver': 'mlx5',
            'pci': '0000:05:00.0',
            'mac': '98:03:9b:67:cb:22',
            'ip': IP(22),
        }
    },
    'oob_ip': '18.26.4.41',
    'node0_cores': range(0, 48, 2),
    'numa_nodes': 2,
}
MACHINES["zig"] = {
    'nics': {
        'enp5s0f0': {
            'driver': 'mlx5',
            'pci': '0000:05:00.0',
            'mac': '98:03:9b:67:cb:2a',
            'ip': IP(21),
        }
    },
    'oob_ip': '18.26.4.39',
    'node0_cores': range(0, 48, 2),
    'numa_nodes': 2,
}
MACHINES.update({
     'pd%d' % d: { 
        'nics': {'10gp1': { 'driver': 'mlx4', 'ip': '10.1.1.%d' % d}},
        'oob_ip': '18.26.5.%d' % d,
        'node0_cores': range(8),
     } for d in range(1, 12)
})
MACHINES['pd8']['nics']['10gp1']['mac'] = "f4:52:14:76:a4:90"
MACHINES['pd11']['nics']['10gp1']['mac'] = "f4:52:14:76:a4:60"
MACHINES['pd10']['nics']['10gp1']['mac'] = "f4:52:14:76:a4:b0"
MACHINES['pd4']['nics']['10gp1']['mac'] = "f4:52:14:76:a4:80"
MACHINES['pd3']['nics']['10gp1']['mac'] = "f4:52:14:76:a1:a0"

binaries = {
    'iokerneld': {
        'ht': "{}/iokerneld".format(SDIR),
    },
    'memcached': {
        'linux': "{}/memcached-linux/memcached".format(BASE_DIR),
        'shenango': "{}/memcached/memcached".format(BASE_DIR),
    },
    'swaptions': {
        'linux': "{}/parsec/pkgs/apps/swaptions/inst/amd64-linux.gcc-pthreads/bin/swaptions".format(BASE_DIR),
        'shenango': "{}/parsec/pkgs/apps/swaptions/inst/amd64-linux.gcc-shenango/bin/swaptions".format(BASE_DIR),
        'linux-floating': "{}/parsec/pkgs/apps/swaptions/inst/amd64-linux.gcc-pthreads/bin/swaptions".format(BASE_DIR),
    },
    'streamcluster': {
        'linux': "{}/parsec/pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster".format(BASE_DIR),
        'shenango': "{}/parsec/pkgs/kernels/streamcluster/inst/amd64-linux.gcc-shenango/bin/streamcluster".format(BASE_DIR),
        'linux-floating': "{}/parsec/pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster".format(BASE_DIR),
    },
    'x264': {
        'linux': '{}/parsec/pkgs/apps/x264/inst/amd64-linux.gcc-pthreads/bin/x264'.format(BASE_DIR),
        'shenango': "{}/parsec/pkgs/apps/x264/inst/amd64-linux.gcc-shenango/bin/x264".format(BASE_DIR),
        'linux-floating': '{}/parsec/pkgs/apps/x264/inst/amd64-linux.gcc-pthreads/bin/x264'.format(BASE_DIR),
    },
    'stress_shm': {
        'shenango': "{}/apps/netbench/stress_shm".format(SDIR),
        'linux': "{}/apps/netbench/stress_linux".format(SDIR),
    },
    'silo': {
        'shenango': '{}/silo/silotpcc-shenango'.format(BASE_DIR),
        'linux': '{}/silo.linux/silotpcc-linux'.format(BASE_DIR),
    },
    'stress_shm_query': {
        'linux': "{}/apps/netbench/stress_shm_query".format(SDIR),
    },
}


def thishost_cores():
    return MACHINES[THISHOST]['node0_cores']

def thishost_shen_cores():
    cores = thishost_cores()
    return cores[1:len(cores)/2] + cores[len(cores)/2+1:]

def max_cores():
    return len(thishost_cores()) - 2

def control_core():
    cores = MACHINES[THISHOST]['node0_cores']
    return cores[len(cores) // 2]

def get_nic(host):
    return list(MACHINES[host]['nics'].values())[0]

def get_nic_name(host):
    return list(MACHINES[host]['nics'].keys())[0]

def get_linux_ip(host):
    return list(MACHINES[host]['nics'].values())[0]['ip']


def gen_conf(filename, experiment, mac=None, **kwargs):
    conf = [
        "host_addr {ip}",
        "host_netmask {netmask}",
        "host_gateway {gw}",
        "runtime_kthreads {threads}",
        "runtime_guaranteed_kthreads {guaranteed}",
        "runtime_spinning_kthreads {spin}"
    ]
    if mac:
        conf.append("host_mac {mac}")

    conf += kwargs.get('custom_conf', [])

    # HACK
    if kwargs['guaranteed'] > 0:
        if not kwargs.get('enable_watchdog', False):
            conf.append("disable_watchdog true")
        conf.append("runtime_priority lc")
    else:
        conf.append("runtime_priority be")

    # if experiment['system'] == "shenango":
    for host in experiment['hosts']:
        for i, cfg in enumerate(experiment['hosts'][host]['apps']):
            if cfg['ip'] == kwargs['ip']:
                continue
            if "shenango" != cfg.get('system', experiment['system']):
                if i == 0:
                    m = list(MACHINES[cfg['host']]['nics'].values())[0]['mac']
                    conf.append("static_arp {ip} {mac}".format(
                        mac=m, ip=cfg['ip']))
            else:
                conf.append("static_arp {ip} {mac}".format(**cfg))

    if experiment.get('observer'):
       obs = experiment['observer']
       observer_nic = list(MACHINES[obs]['nics'].keys())[0]
       observer_mac = MACHINES[obs]['nics'][observer_nic]['mac']
       conf.append("static_arp {} {}".format(OBSERVER_IP, observer_mac))

    with open(filename, "w") as f:
        f.write("\n".join(conf).format(
            netmask=NETMASK, gw=GATEWAY, mac=mac, **kwargs) + "\n")
