from experiment import *
from time import sleep
from caladan_common import *
import random

# controls how many samples are collected (and duration) for experiments
# that sweep multiple QPSs. Add more time for better quality samples.
NSAMPLES = 10
TIME = 5


def ksched_stress(config='caladan', be='sqrt', spin=False, name=None):
    nn = "-{}-{}".format(config, be)
    if name:
        nn += "-" + name
    if spin:
        nn += "-spinning"
    x = new_experiment(conf_to_sysname(config), name=nn)

    cs = []

    NR_BE = 2
    NR_BE_CORES = max_cores()

    NR_LC = 11
    NR_LC_CORES = 2

    if len(CLIENT_SET) * 3 < NR_LC:
        print("WARNING - this experiment requires several client machines.")

    for i in range(NR_BE):
        bex, sq = BE_CONFIGS[be](NR_BE_CORES, x, name="be{}".format(i))
        bex['iters'] *= 10

    for i in range(NR_LC):
        ms = new_synthetic_server(NR_LC_CORES, x, name='synth{}'.format(i))
        if spin:
            ms['spin'] = ms['threads']
        cs += new_measurement_instances(1, ms, 0.4, x,
                                        nconns=64, distribution='exponential', mean=376)

    finalize_measurement_cohort(cs, x, NSAMPLES, TIME)

    for c in cs:
        c['before'] = c.get('before', []) + ['sleep_5'] * 5

    configure_experiment(config, x)
    execute_experiment(x)


def memcached_trace(config='caladan'):
    x = new_experiment(conf_to_sysname(config),
                       name="-{}-memcached_trace".format(config))

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
        c['args'] += " --loadshift={}:{}".format(
            int(mpps * 1e6), int(time * 1e6))
        c['output'] = 'trace'

    finalize_measurement_cohort(ch, x, 1, time)

    be, tracer = BE_CONFIGS["swaptionsGC"](max_cores(), x)
    tracer['frequency_us'] = 1000

    x['hosts'][THISHOST]['hugepages'] = 4000
    configure_experiment(config, x)
    execute_experiment(x)


def lc_sweep(lc='memcached', be='streamcluster', config='caladan', samples=NSAMPLES, time=TIME, start_mpps=None, mpps=None, htparam=None, silomppsoverride=None, coreoverride=None, becoreoverride=None, name=None, **kwargs):
    nn = "-{}-{}-{}".format(config, lc, be)
    if name:
        nn += "-" + name
    x = new_experiment(conf_to_sysname(config), name=nn)

    cores = coreoverride or conf_name_get_max_cores(config)
    becores = becoreoverride or cores
    start_mpps = start_mpps if start_mpps is not None else 0

    if lc == 'memcached':
        mpps = mpps or min(12.0, conf_get_max_pps(config))
        l = new_memcached_server(cores, x)
        ch = new_measurement_instances(
            len(CLIENT_SET), l, mpps, x, nconns=400, start_mpps=start_mpps, **kwargs)
        for c in ch:
            c['args'] += " --nvalues=32000000"
    elif lc == 'silo':
        if mpps is None:
            rep_external_partial(lc_sweep, start_mpps, silomppsoverride or 0.65,
                                 samples, lc=lc, be=be, config=config, time=time, htparam=htparam, name=name)
            return
        l = new_silo_server(cores, x)
        l['mem'] = 3 * (1 << 30)
        ch = new_measurement_instances(
            1, l, mpps, x, nconns=64, mean=0, rampup=1, start_mpps=start_mpps)
        time = min(60, time)
        htparam = 25 if htparam is None else htparam
    elif lc == 'storage':
        l, ch = storage(cores, x, mpps, start_mpps=start_mpps, **kwargs)
        htparam = 40 if htparam is None else htparam
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


def multi_time_step(cfg='caladan', trace_enabled=True):
    nn = "-" + cfg + "-multiapp"
    x = new_experiment("shenango", name=nn)

    STEPS = 4
    MEMC_T = 6
    SILO_T = 6
    STORAG_T = 6
    BURST_ENABLED = True
    HT_CONTROLLER_ENABLED = True
    spin = False

    lcs = ["memcached", "silo", "storage"]
    ch = []

    if "memcached" in lcs:
        mc = new_memcached_server(MEMC_T, x)
        newcs = new_measurement_instances(
            2, mc, 10 * MEMC_T / 22.0, x, nconns=200)
        if BURST_ENABLED:
            mc['threads'] = max_cores()
        if spin:
            mc['spin'] = MEMC_T
        for c in newcs:
            c['args'] += " --nvalues=32000000"
        ch += newcs
        mc['after'] += ['sleep_5'] * 8 + ['mon_mem_bw']
        mc['args'] = mc['args'].replace(",slab_reassign", ",no_slab_reassign")
        mc['args'] = mc['args'].replace(
            ",lru_maintainer,", ",no_lru_maintainer,")
        mc['args'] = mc['args'].replace(",lru_crawler,", ",no_lru_crawler,")

    if "silo" in lcs:
        sl = new_silo_server(SILO_T, x)
        sl['mem'] = 6 * (1 << 30)
        if BURST_ENABLED:
            sl['threads'] = max_cores()
        if HT_CONTROLLER_ENABLED:
            sl['custom_conf'].append('runtime_ht_punish_us 25')
        if spin:
            sl['spin'] = SILO_T
        ch += new_measurement_instances(1, sl,
                                        0.50 * SILO_T / 22.0, x, nconns=200)

    if "storage" in lcs:
        st = new_storage_server(STORAG_T, x)
        if BURST_ENABLED:
            st['threads'] = max_cores()
        if HT_CONTROLLER_ENABLED:
            st['custom_conf'].append('runtime_ht_punish_us 40')
        if spin:
            st['spin'] = STORAG_T
        ch += new_measurement_instances(1, st, 0.293979 * STORAG_T / 22.0, x,
                                        nconns=75, mean=16, distribution="bimodal1", client_list=['zag'])

    for be in ["streamcluster", "swaptionsGC"]:
        be, tracer = BE_CONFIGS[be](max_cores(), x)
        if trace_enabled:
            tracer['frequency_us'] = 1000

    for c in ch:
        mload = c['mpps']

        c['before'] += ['sleep_5'] * 6

        loads = []
        loads.append((1e6 * mload * 0.03, 5e6, 0))
        loads.append((1e6 * mload * 0.5, 2e5, 0))
        loads.append((1e6 * mload * 0.75, 2e5, 0))
        loads.append((1e6 * mload * 1, 2e5, 0))
        loads.append((1e6 * mload * 0.03, 5e6, 0))
        loads.append((1e6 * mload * 0.03, 1e6))
        loads.append((1e6 * mload * 0.03, 1e6))
        loads.append((1e6 * mload * 0.03, 1e6))

        loads += [(0.5 * 1e6 * mload / STEPS, 1e6)]
        for i in range(1, int(STEPS) + 1):
            loads.append((1e6 * mload * i / STEPS, 4e6))
            if trace_enabled:
                loads.append((0.5 * 1e6 * mload / STEPS, 4e6))

        loads = map(lambda f: ":".join(map(str, map(int, f))), loads)
        loads = " --loadshift=" + ",".join(loads)
        c['args'] += loads
        if trace_enabled:
            c['output'] = 'trace'

    finalize_measurement_cohort(ch, x, 10, 10)

    configure_experiment(cfg, x)
    x['hosts'][THISHOST]['hugepages'] = 5572
    execute_experiment(x)


def figure_7_lc_be_combos():
    for lc in ["memcached", "storage", "silo"]:
        for be in ["x264", "streamcluster", "streamDRAM", "swaptionsGC", None]:
            lc_sweep(lc=lc, be=be, name="figure_7")


def figure_6_timeseries():
    memcached_trace()


def figure_8_multi_app_timeseries():
    multi_time_step()


def figure_9b_scheduling():
    ksched_stress(name="figure_9b_ksched")
    ksched_stress(spin=True, name="figure_9b_pinned")


def figure_9c_controllers():
    lc_sweep(lc='storage', be='streamDRAM', config='caladan_nobw',
             htparam=0, name="figure_9c_No_Controllers")
    lc_sweep(lc='storage', be='streamDRAM', config='caladan',
             htparam=0, name="figure_9c_BW")
    lc_sweep(lc='storage', be='streamDRAM',
             config='caladan', name="figure_9c_BW_and_HT")
    lc_sweep(lc='storage', be=None, config='caladan',
             name="figure_9c_No_Colocation")

def main():
    figure_7_lc_be_combos()
    figure_8_multi_app_timeseries()
    figure_9b_scheduling()
    figure_9c_controllers()
    figure_6_timeseries()

    pass

if __name__ == '__main__':
    main()
