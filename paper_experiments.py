
from experiment import *
from time import sleep
from caladan_common import *
import random


NSAMPLES = 10
TIME = 30

def scheduling_test(config='caladan', be=None):
    nn = "-{}-{}".format(config, be)
    x = new_experiment(conf_to_sysname(config), name=nn)

    del x['observer']
    cl = [OBSERVER] + CLIENT_SET
    cs = []

    NR_BE = 2
    NR_BE_CORES = max_cores()

    NR_LC = 11
    NR_LC_CORES = 2

    for i in range(NR_BE):
        bex, sq = BE_CONFIGS[be](NR_BE_CORES, x, name="be{}".format(i))
        bex['iters'] *= 10
        # if be == "sqrt":
        #     lc = new_stress_inst(NR_BE_CORES, x, name='stress{}'.format(i))
        #     del lc['timestamp']
        # elif be == "f":
        #     lc = new_stress_inst(NR_BE_CORES, x, name='stress{}'.format(i))
        #     lc['fakework'] = 'cacheantagonist:2200000:0:11rw'
        #     lc['iters'] = 10
        #     del lc['timestamp']

    for i in range(NR_LC):
        ms = new_synthetic_server(NR_LC_CORES, x, name='synth{}'.format(i))
        cs += new_measurement_instances(1, ms, 0.4, x, nconns=64, distribution='exponential', mean=376, client_list=cl)

    finalize_measurement_cohort(cs, x, 20, 5)

    for c in cs:
        c['before'] = c.get('before', []) + ['sleep_5']*5
        # c['mean'] = 10 * 1000.0 / 16.51699149

    configure_experiment(config, x)
    execute_experiment(x)

def memcached_trace(config='caladan'):
    x = new_experiment(conf_to_sysname(config), name="-memcached_trace")

    mpps = 0.8
    time = 20

    l = new_memcached_server(max_cores(), x)
    l['args'] = l['args'].replace(",slab_reassign", ",no_slab_reassign")
    l['args'] = l['args'].replace(",lru_maintainer,", ",no_lru_maintainer,")
    l['args'] = l['args'].replace(",lru_crawler,", ",no_lru_crawler,")
    ch = new_measurement_instances(1, l, mpps, x, nconns=64)
    for c in ch:
        c['args'] += " --nvalues=32000000"

    l['after'] = l.get('after', [])
    l['before'] = l.get('before', [])
    l['before'] += ['sleep_5'] * 6
    l['after'].append('release_clients')
    x['manual_client_release'] = True
    l['after'] += ['sleep_5'] * 8 + ['mon_mem_bw']
    for c in ch:
        c['args'] += " --loadshift={}:{}".format(int(mpps * 1e6), int(time*1e6))
        c['output'] = 'trace'

    finalize_measurement_cohort(ch, x, 1, time)


    be, tracer = BE_CONFIGS["swaptionsGC"](max_cores(), x)
    tracer['frequency_us'] = 1000

    x['hosts'][THISHOST]['hugepages'] = 4000
    configure_experiment(config, x)
    execute_experiment(x)


def lc_sweep(lc='memcached', be='streamcluster', config='caladan', samples=NSAMPLES, time=TIME, start_mpps=None, mpps=None, htparam=None, silomppsoverride=None, coreoverride=None, becoreoverride=None,  **kwargs):
    nn = "-{}-{}-{}".format(config, lc, be)
    x = new_experiment(conf_to_sysname(config), name=nn)

    cores = coreoverride or conf_name_get_max_cores(config)
    becores = becoreoverride or cores
    start_mpps = start_mpps if start_mpps is not None else 0

    if lc == 'memcached':
        mpps = mpps or min(12.0, conf_get_max_pps(config))
        l = new_memcached_server(cores, x)
        ch = new_measurement_instances(len(CLIENT_SET), l, mpps, x, nconns=400, start_mpps=start_mpps, **kwargs)
        for c in ch:
            c['args'] += " --nvalues=32000000"
    elif lc == 'silo':
        if mpps is None:
            rep_external_partial(lc_sweep, start_mpps, silomppsoverride or 0.65, samples, lc=lc, be=be, config=config, time=time, htparam=htparam)
            return
        l = new_silo_server(cores, x)
        l['mem'] = 3 * (1 << 30)
        ch = new_measurement_instances(1, l, mpps, x, nconns=64, mean=0, rampup=1, start_mpps=start_mpps)
        time = min(60, time)
        htparam = 25 if htparam is None else htparam
    elif lc == 'storage':
        l, ch = storage(cores, x, mpps, start_mpps=start_mpps, **kwargs)
        htparam = 40 if htparam is None else htparams
    else:
        assert False

    finalize_measurement_cohort(ch, x, samples, time)

    if htparam is not None:
        l['custom_conf'].append('runtime_ht_punish_us {}'.format(htparam))

    if be is not None:
        be_constructor = BE_CONFIGS[be]
        be, sq = be_constructor(becores, x)

    configure_experiment(config, x)
    if lc == 'silo':
        x['hosts'][THISHOST]['hugepages'] = 3500
        return x

    try:
        execute_experiment(x)
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        pass

def multi_time_step(
            cfg, ht_en=True, spin=False, burst=True, be=True, trace_enabled=True,
                 lcs=["memcached", "silo", "storage"],
                 load_points=4,
                 disable_bg_tasks=False, be_select=["streamcluster", "swaptionsGC"]):

    nn = "-multi"
    if ht_en: nn += "-ht_controller"
    if spin: nn += "-spin"
    if burst: nn += "-burst"
    if be: nn += "-be"
    x = new_experiment("shenango", name=nn)

    STEPS = load_points
    MEMC_T = 6
    SILO_T = 6
    STORAG_T = 6

    BURST_ENABLED = burst
    HT_CONTROLLER_ENABLED = ht_en

    ch = []

    if "memcached" in lcs:
        mc = new_memcached_server(MEMC_T, x)
        newcs = new_measurement_instances(2, mc, 10 * MEMC_T / 22.0, x, nconns=200)
        if BURST_ENABLED: mc['threads'] = max_cores()
        if spin: mc['spin'] = MEMC_T
        for c in newcs:
            c['args'] += " --nvalues=32000000"
        ch += newcs
        mc['after'] += ['sleep_5'] * 8 + ['special_mon']
        if disable_bg_tasks:
            mc['args'] = mc['args'].replace(",slab_reassign", ",no_slab_reassign")
            mc['args'] = mc['args'].replace(",lru_maintainer,", ",no_lru_maintainer,")
            mc['args'] = mc['args'].replace(",lru_crawler,", ",no_lru_crawler,")

    if "silo" in lcs:
        sl = new_silo_server(SILO_T, x)
        sl['mem'] = 6 * (1 << 30)
        if BURST_ENABLED: sl['threads'] = max_cores()
        if HT_CONTROLLER_ENABLED: sl['custom_conf'].append('runtime_ht_punish_us 25')
        if spin: sl['spin'] = SILO_T
        ch += new_measurement_instances(2, sl, 0.50 * SILO_T / 22.0, x, nconns=200)

    if "storage" in lcs:
        st = new_storage_server(STORAG_T, x)
        if BURST_ENABLED: st['threads'] = max_cores()
        if HT_CONTROLLER_ENABLED: st['custom_conf'].append('runtime_ht_punish_us 40')
        if spin: st['spin'] = STORAG_T
        ch += new_measurement_instances(1, st, 0.293979 * STORAG_T / 22.0, x, nconns=75, mean=16, distribution="bimodal1", client_list=['zag'])

    if be:
        for be in be_select:
          be, tracer = BE_CONFIGS[be](max_cores(), x)
          if trace_enabled:
            tracer['frequency_us'] = 1000

    for c in ch:
        mload = c['mpps']

        if "swaptionsGC" in be_select:
            c['before'] += ['sleep_5'] * 6

        loads = [] #
        loads.append((1e6 * mload * 0.03, 5e6, 0))
        loads.append((1e6 * mload * 0.5, 2e5, 0))
        loads.append((1e6 * mload * 0.75, 2e5, 0))
        loads.append((1e6 * mload * 1, 2e5, 0))
        loads.append((1e6 * mload * 0.03, 5e6,0))
        loads.append((1e6 * mload * 0.03, 1e6))
        loads.append((1e6 * mload * 0.03, 1e6))
        loads.append((1e6 * mload * 0.03, 1e6)) 
        # if "memcached" in lcs and not disable_bg_tasks:
        #     loads.append((1e6 * mload * 0.03, 40e6, 0))


        # loads += [(0, 1e6, 0)]
        loads += [(0.5 * 1e6 * mload/ STEPS, 1e6)]
        for i in range(1, int(STEPS) + 1):
            loads.append((1e6 * mload * i / STEPS, 4e6))
            if trace_enabled:
                loads.append((0.5 * 1e6 * mload / STEPS, 4e6))


        # loads = [(1e6 * mload/ STEPS, 1e6)] + [
        #     (1e6 * mload * i / STEPS, 2e5) for i in range(1, int(STEPS) + 1)
        # ]

        rampup = [] #(l[0], 5e5, 0) for l in loads[:len(loads)//2]]

        loads = map(lambda f: ":".join(map(str, map(int, f))), rampup + loads)
        loads = " --loadshift=" + ",".join(loads)
        c['args'] += loads
        if trace_enabled:
            c['output'] = 'trace'


    finalize_measurement_cohort(ch, x, 10, 10)

    configure_experiment(cfg, x)
    x['hosts'][THISHOST]['hugepages'] = 5572
    execute_experiment(x)

def main():
    # memcached_trace()
    for lc in ["silo"]:
        for be in ["streamDRAM", "swaptionsGC", None]:
            lc_sweep(lc=lc, be=be, config='caladan', samples=10, time=5)

    # lc_sweep(lc='memcached', be='hammer', config='caladan_mutualpair', samples=20, time=30)
    pass

if __name__ == '__main__':
    main()
