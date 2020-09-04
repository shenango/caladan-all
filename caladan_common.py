from env import *
from experiment import *

def new_stress_shm_inst(threads, experiment, **kwargs):
    x = {
        'name': "stress_shm",
        'ip': alloc_ip(experiment, **kwargs),
        'port': None,
        'mac': gen_random_mac(),
        'threads': threads,
        'guaranteed': 0,
        'spin': 0,
        'app': 'stress_shm',
        'nice': 20,
        'fakework': 'sqrt',
        'iters': 100000,
        'args': "{uthreads} {iters} {fakework}",
        'uthreads': threads,
        'shmkey': 0x123,
        'timestamp': True,
    }
    x.update(kwargs)
    add_app(experiment, x, **kwargs)
    return x

def new_silo_server(threads, experiment, **kwargs):
    x = {
        'system': kwargs.get('system', experiment['system']),
        'name': kwargs.get('name', 'silo'),
        'ip': alloc_ip(experiment),
        'port': alloc_port(experiment),
        'threads': threads,
        'guaranteed': threads,
        'spin': 0,
        'app': 'silo',
        'nice': -20,
        'mac': gen_random_mac(),
        'protocol': 'synthetic',
        'transport': kwargs.get('transport', 'tcp'),
        'args': '{threads} {port} {mem}',
        'mem': 14 * (1 << 30),
        'env': ["LD_LIBRARY_PATH={}/silo/silo/third-party/lz4".format(BASE_DIR)],
        'after': ['sleep_5', 'sleep_5', 'release_clients'],
    }

    assert not experiment.get('manual_client_release')
    experiment['manual_client_release'] = True
    add_app(experiment, x)
    return x

def new_storage_server(threads, experiment, **kwargs):
    system = kwargs.get('system', experiment['system'])
    binary = {
        'linux': '{}/apps/storage_service/storage_server_linux'.format(SDIR),
        'shenango': '{}/apps/storage_service/storage_server'.format(SDIR),
    }[system]
    x = {
        'binary': binary,
        'name': kwargs.get('name', "storage"),
        'ip': alloc_ip(experiment, **kwargs),
        'port': 5000, #alloc_port(experiment),
        'threads': threads,
        'guaranteed': threads,
        'spin': 0,
        'app': 'storage_service',
        'nice': -20,
        'mac': gen_random_mac(),
        'protocol': 'reflex',
        'transport': 'tcp',
        'system': system,
        'custom_conf': ["enable_storage 1", "enable_directpath 1"]
    }

    if system == "linux":
        x['sudo'] = True
        x['flashpath'] =  FLASHPATH
        x['cFCFS'] = kwargs.get('cFCFS', 1)
        x['args'] = "{threads} {port} {flashpath} {cFCFS}"
    else:
        x['args'] = "{port}"

    add_app(experiment, x, **kwargs)
    return x

def new_streamcluster_inst(threads, experiment, **kwargs):
    sys = kwargs.get('system', experiment.get('system'))
    x = {
        'name': kwargs.get('name', "streamcluster"),
        'ip': alloc_ip(experiment, **kwargs),
        'port': None,
        'mac': gen_random_mac(),
        'threads': threads,
        'guaranteed': 0,
        'spin': 0,
        'app': 'streamcluster',
        'nice': 20,
        # 'point_dim': 40960,
        'uthreads': 100,
        'args': "10 20 8192 10000 10000 5000 none output.txt {uthreads}",
        'timestamp': True,
        # 'args': "10 20 {point_dim} 1000000 1000 5000 none none 100 2>&1 | ts %s",
    }
    if sys == "linux": x['uthreads'] = threads
    x.update(kwargs)
    add_app(experiment, x, **kwargs)
    return x

def new_x264_inst(threads, experiment, **kwargs):
    x = {
        'name': "x264",
        'ip': alloc_ip(experiment, **kwargs),
        'port': None,
        'mac': gen_random_mac(),
        'threads': threads,
        'guaranteed': 0,
        'spin': 0,
        'app': 'x264',
        'nice': 20,
        'timestamp': True,
        'args': "--quiet --qp 20 --partitions b8x8,i4x4 --ref 5 --direct auto --b-pyramid --weightb --mixed-refs --no-fast-pskip --me umh --subme 7 --analyse b8x8,i4x4 --threads 128 -o /dev/null ~friedj/eledream_1920x1080_512.y4m"
    }
    x.update(kwargs)
    add_app(experiment, x, **kwargs)
    return x

def new_stress_shm_query(app, experiment):
    y = {
        'name': "{}_shm_query".format(app['name']),
        'system': 'linux',
        'ip': alloc_ip(experiment, system="linux"),
        'port': None,
        'mac': gen_random_mac(),
        'threads': 1,
        'appthreads': app['threads'],
        'guaranteed': 0,
        'spin': 0,
        'nice': 0,
        'app': 'stress_shm_query',
        'frequency_us': 1000 * 100,
        'args': "{shmkey}:{frequency_us}:{appthreads}",
        'shmkey': app['shmkey'],
        'timestamp': False,
        'ping_deps': [app['ip']],
        'before': ['sleep_5'],
    }
    if MACHINES[THISHOST]['numa_nodes'] > 1:
        y['numa_node'] = '1'
        y['numa_memory'] = 'all'
    else:
        y['corelimit'] = str(control_core())
    add_app(experiment, y)
    return y

def new_swaptionsGC(thrs, experiment, **kwargs):
    if 'name' not in kwargs: kwargs['name'] = 'swaptionsGC'
    s = new_swaptions_inst(thrs, experiment, **kwargs)
    if experiment['system'] == "shenango":
        s['binary'] = "{}/parsec/pkgs/apps/swaptions/inst/amd64-linux.gcc-shenango-gc/bin/swaptions".format(BASE_DIR)
        s['env'] = []
        s['custom_conf'].append("enable_gc 1")
    elif experiment['system'] == 'linux':
        assert False, "Todo - support linux"
    else:
        assert False, experiment['system']

    s['nswaptions'] = 5000000
    s['simulations'] = 400
    s['shmkey'] = int(s['ip'].split(".")[-1])
    s['env'] += ['SHMKEY=%d' % s['shmkey']]
    sq = new_stress_shm_query(s, experiment)
    return s, sq

def streamcluster(cores, experiment, **kwargs):
    be = new_streamcluster_inst(cores, experiment, **kwargs)
    be['shmkey'] = int(random.uniform(1, 65535))
    be['env'] = ['SHMKEY=%d' % be['shmkey']]
    be_st = new_stress_shm_query(be, experiment)
    be_st['appthreads'] = be['uthreads']
    return be, be_st

def x264(cores, experiment):
    be = new_x264_inst(cores, experiment)
    be['shmkey'] = int(random.uniform(1, 65535))
    be['env'] = ['SHMKEY=%d' % be['shmkey']]
    be_st = new_stress_shm_query(be, experiment)
    be_st['appthreads'] = 1
    return be, be_st

def hammer(cores, experiment, **kwargs):
    if 'name' not in kwargs: kwargs['name'] = "streamDRAM"
    lc = new_stress_shm_inst(cores, experiment, **kwargs)
    lc['fakework'] = 'cacheantagonist:4090880'
    lc['iters'] = 10
    s = new_stress_shm_query(lc, experiment)
    return lc, s

def sqrt(cores, experiment, **kwargs):
    lc = new_stress_shm_inst(cores, experiment, **kwargs)
    s = new_stress_shm_query(lc, experiment)
    return lc, s

def hammersmall(cores, experiment, **kwargs):
    lc = new_stress_shm_inst(cores, experiment, **kwargs)
    lc['fakework'] = 'cacheantagonist:2000000'
    lc['iters'] = 10
    s = new_stress_shm_query(lc, experiment)
    return lc, s

BE_CONFIGS = {
    'swaptionsGC': new_swaptionsGC,
    'streamcluster': streamcluster,
    'x264': x264,
    'streamDRAM': hammer,
    'hammersmall': hammersmall,
    'sqrt': sqrt,
}

def new_synthetic_server(threads, experiment, **kwargs):
    x = {
        'name': kwargs.get('name', 'synth'),
        'ip': alloc_ip(experiment),
        'port': alloc_port(experiment),
        'threads': threads,
        'guaranteed': threads,
        'spin': 0,
        'app': 'synthetic',
        'nice': -20,
        'mac': gen_random_mac(),
        'protocol': 'synthetic',
        'transport': kwargs.get('transport', 'tcp'),
        'fakework': kwargs.get('fakework', 'stridedmem:1024:7'),
        'args': "--mode={stype}-server {ip}:{port} --threads {threads} --transport {transport}"
    }

    x['args'] += " --fakework {fakework}"
    if experiment["system"] == "shenango":
        x['stype'] = 'spawner'
    elif "linux" in experiment['system']:  # == "linux-floating":
        x['args'] = "{fakework} {threads} {port}"
    add_app(experiment, x, **kwargs)
    return x


def configure_caladan(name, experiment, host=None):
    host = host or THISHOST
    options = []
    if "nobw" in name: options.append("nobw")
    if "selfpair" not in name: options.append("mutualpair")

    sched = 'ias'
    if "SIMPLE" in name:
        sched = 'simple'
    set_scheduler(sched, experiment, options=options, host=host)

    for app in experiment['hosts'][host]['apps']:
        a = app['app']
        if a in ['memcached', 'silo', 'synthetic', 'storage_service']:
            if "spinall" in name: app['spin'] = app['threads']
            enable_directpath(app)

            if "noqdel" not in name:
                 app['custom_conf'].append("runtime_qdelay_us 10")

        elif a in ["stress_shm_query", "stress_shm", "streamcluster", "swaptions", "x264", "sleep"]:
            pass
        else:
            assert False, a

def configure_experiment(name, experiment, **kwargs):
    configure_caladan(name, experiment, **kwargs)

def conf_name_get_max_cores(name):
    return max_cores() + (2 if name == "linux" else 0)

def conf_get_max_pps(name):
    return {
        'linux': 1.6,
        'shenango': 5.0,
    }.get(name, 24.0)

def conf_to_sysname(name):
    return {
        'linux': 'linux',
    }.get(name, "shenango")


def storage(cores, experiment, mpps=None, **kwargs):
    l = new_storage_server(cores, experiment)

    mpps = mpps or 0.33
    start_mpps = kwargs.get('start_mpps', 0)
    dist = kwargs.get('distribution', 'bimodal1')
    ch = new_measurement_instances(1, l, mpps, experiment, nconns=400, client_list=['zag'], mean=16, distribution=dist, start_mpps=start_mpps)
    return l, ch

def mon_mem_bw(cfg, experiment):
    x = launch("sudo numactl -N1 {}/apps/netbench/stress_shm_query membw:1000 > mem.log 2>&1".format(SDIR),
               cwd=experiment['name'])
    experiment['tm'].monitor_in_thread(x)

register_fn('mon_mem_bw', mon_mem_bw)

