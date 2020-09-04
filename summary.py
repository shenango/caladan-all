
# usage: python summary.py <experiment directory>

from __future__ import print_function

import json
import os
import sys
from collections import defaultdict
import re
from globals import except_none
from heapq import merge

AGGREGATE_ALL_APPS = False

if AGGREGATE_ALL_APPS:
    print("WARNING: AGGREGATING MULTIPLE APPS INTO ONE")

def maybe_trim(l):
    try:
        lx = l.split(" ", 1)
        int(lx[0])
        return lx[1]
    except:
        return l

def percentile(latd, target):
    # latd: ({microseconds: count}, number_dropped)
    # target: percentile target, ie 0.99
    latd, dropped = latd
    count = sum([latd[k] for k in latd]) + dropped
    target_idx = int(float(count) * target)
    curIdx = 0
    for k in sorted(latd.keys()):
        curIdx += latd[k]
        if curIdx >= target_idx:
            return k
    return float("inf")


def read_lat_line(line):
    line = maybe_trim(line)  # line.split(" ", 1)[1]
    if line.startswith("Latencies: "):
        line = line[len("Latencies: "):]
    d = {}
    for l in line.strip().split():
        if ":" not in l:
            break
        micros, count = l.split(":")
        if not count or not micros:
            break
        d[int(micros)] = int(count)
    return d


def read_trace_line(line):
    if line.startswith("Trace: "):
        line = line[len("Trace: "):]
    points = []
    lats = defaultdict(int)
    tsc = 0
    for l in line.strip().split():
        ls = l.split(":")
        if len(ls) != 4: continue
        start, delay, latency, ntsc = ls
        if ntsc == '': print(l)
        ntsc = int(ntsc)
        assert ntsc >= tsc, str(ntsc) + " " + str(tsc)
        tsc = ntsc
        if not latency:
            continue
        if latency != "-1":
            lats[int(latency) // 1000] += 1
        if delay != "-1":
            points.append((tsc, int(latency)//1000))
    return lats, points


# list_of_tuples: [({microseconds: count}, number_dropped)...]
def merge_lat(list_of_tuples):
    dropped = 0
    c = defaultdict(int)
    for s in list_of_tuples:
        for k in s[0]:
            c[k] += s[0][k]
        dropped += s[1]
    return c, dropped


def parse_loadgen_output(filename):
    with open(filename) as f:
        dat = f.read()

    samples = []

    line_starts = ["Latencies: ", "Trace: ", "zero, ", "exponential, ",
                   "bimodal1, ", "constant, ", "bimodal3, "]

    def get_line_start(line):
        for l in line_starts:
            if line.startswith(l):
                return l
        return None

    """Distribution, Target, Actual, Dropped, Never Sent, Median, 90th, 99th, 99.9th, 99.99th, Start, Starts_TSC"""
    header_line = None
    for line in dat.splitlines():
        line = maybe_trim(line)  # line.split(" ", 1)[1]
        line_start = get_line_start(line)
        if not line_start:
            continue
        if line_start == "Latencies: ":
            samples.append({
                'distribution': header_line[0],
                'offered': int(header_line[1]),
                'achieved': int(header_line[2]),
                'missed': int(header_line[4]),
                'latencies': (read_lat_line(line), int(header_line[3])),
                'time': int(header_line[10]),
            })
            if len(header_line) > 11:
                samples[-1]['time_tsc'] = int(header_line[11])
        elif line_start == "Trace: ":
            lats, tracepoints = read_trace_line(line)
            samples.append({
                'distribution': header_line[0],
                'offered': int(header_line[1]),
                'achieved': int(header_line[2]),
                'missed': int(header_line[4]),
                'latencies': (lats, int(header_line[3])),
                'tracepoints': tracepoints,
                'time': int(header_line[10]),
            })
            if len(header_line) > 11:
                samples[-1]['time_tsc'] = int(header_line[11])
        else:
            header_line = line.strip().split(", ")
            assert len(header_line) > 10 or len(header_line) == 6, line
            if len(header_line) == 6:
                samples.append({
                    'distribution': header_line[0],
                    'offered': int(header_line[1]),
                    'achieved': 0,
                    'missed': int(header_line[4]),
                    'latencies': ({}, int(header_line[3])),
                    'time': int(header_line[5]),
                })
    return samples


def merge_sample_sets(a, b):
    samples = []
    for ea, eb in zip(a, b):
        assert set(ea.keys()) == set(eb.keys())
        assert ea['distribution'] == eb['distribution']
        # assert ea['app'] == eb['app']
        if not abs(ea['time'] - eb['time']) < 2:
            print("truncating", ea['time'], eb['time'])
            return samples
        newexp = {
            'distribution': ea['distribution'],
            'offered': ea['offered'] + eb['offered'],
            'achieved': ea['achieved'] + eb['achieved'],
            'missed': ea['missed'] + eb['missed'],
            'latencies': merge_lat([ea['latencies'], eb['latencies']]),
            # 'app': ea['app'],
            'time': min(ea['time'], eb['time']),
        }
        if 'time_tsc' in ea or 'time_tsc' in eb:
            newexp['time_tsc'] = min(ea['time_tsc'], eb['time_tsc'])
        if 'tracepoints' in ea:
            newexp['tracepoints'] = merge(ea['tracepoints'], eb['tracepoints'])
        samples.append(newexp)
        assert set(ea.keys()) == set(newexp.keys())
    return samples


@except_none
def load_shm_query(experiment, app, directory):
    filename = "{}/{}.out".format(directory, app['name'])
    assert os.access(filename, os.F_OK)
    with open(filename) as f:
        bgdata = f.read().splitlines()

    points = []
    lastx = None

    assert "shm_query" in app['name']

    cycles_per_us = None
    for l in bgdata:
        if "ticks / us" in l:
            cycles_per_us = int(l.split("detected")[1].split()[0])
            continue
        try:
            ls = l.split()
            tsc = int(ls[-1])
            ops = int(ls[-2])
            shmkey = int(ls[-3], 16)
        except:
            continue

        # lx = l.strip().split()
        ll = lastx
        lastx = tsc #int(lx[-1])
        if ll is None:
            continue
        y = float(ops)
        if y == 0.0:
            points.append((None, 0, lastx))
            continue
        cycles_per_op = (lastx - ll) / y
        cycles_per_s = 2197.0 * float(1e6)
        points.append((None, cycles_per_s / cycles_per_op, lastx))

    return {
        'recorded_baseline': None,
        'w_datapoints': all_windows(experiment, points, use_tsc=True, cycles_per_us=cycles_per_us)
    }


def extract_window(datapoints, wct_start, duration_sec, tsc_start=None, cycles_per_us=None):

    d_index = 0

    if tsc_start is not None:
        # do datapoints have a tsc attached
        assert all(len(d) == 3 for d in datapoints)

        assert cycles_per_us is not None
        duration_sec = cycles_per_us * 1e6 * duration_sec
        wct_start = tsc_start
        d_index = 2

    assert datapoints

    window_start = wct_start + int(duration_sec * 0.2)
    window_end = wct_start + int(duration_sec * 0.8)

    datapoints = list(filter(lambda l: l[d_index] >= window_start and l[
        d_index] <= window_end, datapoints))

    # Weight any gaps in reporting
    try:
        total = 0
        nsecs = 0
        for idx, dp in enumerate(datapoints[1:]):
            tm = dp[d_index]
            rate = dp[1]
            nsec = tm - datapoints[idx][d_index]
            total += rate * nsec
            nsecs += nsec
        avgmids = total / nsecs
    except:
        avgmids = None

    return avgmids


def all_windows(experiment, datapoints, use_tsc=False, cycles_per_us=None):
    rt = experiment.get('runtime')
    if not use_tsc:
        times = experiment.get('sample_starts')
        return [extract_window(datapoints, t, rt) for t in times]
    else:
        times = experiment.get('sample_starts_tsc')
        return [extract_window(datapoints, None, rt, t, cycles_per_us) for t in times]


def load_loadgen_results(experiment, dirname):
    # bubble out a few globals for convenience:
    # nsamples, WCTs, runtimes
    sample_starts = []
    sample_starts_tsc = []
    nsamples = None
    runtime = None
    app = None

    for inst in experiment['loadgens']:
        filename = "{}/{}.out".format(dirname, inst['name'])
        assert os.access(filename, os.F_OK)
        assert "runtime-client" in inst[
            'args'] or "local-client" in inst['args']
        data = parse_loadgen_output(filename)
        if inst['name'] != "localsynth":
            server_handle = inst.get('app_name')
            if not server_handle:  # support legacy case
                server_handle = inst['name'].split(".")[1]
            if not AGGREGATE_ALL_APPS or not app:
                app = experiment['apps'][server_handle]
        else:
            app = inst
        if not 'loadgen' in app:
            app['loadgen'] = data
        else:
            app['loadgen'] = merge_sample_sets(app['loadgen'], data)

        start_times = [s['time'] for s in app['loadgen']]
        if not sample_starts:
            sample_starts = start_times
        if len(start_times) != len(sample_starts):
          slen = min(len(start_times), len(sample_starts))
          start_times = start_times[:slen]
          sample_starts = sample_starts[:slen]
          assert slen, filename
        for a, b in zip(start_times, sample_starts):
            assert (a - b)**2 <= 1

        start_tscs = [s.get('time_tsc') for s in app['loadgen']]
        start_tscs = list(filter(lambda a: a, start_tscs))
        if start_tscs:
            if not sample_starts_tsc:
                sample_starts_tsc = start_tscs
            if len(sample_starts_tsc) != len(start_tscs):
                mlen = min(len(sample_starts_tsc), len(start_tscs))
                sample_starts_tsc = sample_starts_tsc[:mlen]
                start_tscs = start_tscs[:mlen]
                assert mlen
            assert len(sample_starts_tsc) == len(start_tscs)
            sample_starts_tsc = list(map(min, zip(sample_starts_tsc, start_tscs)))

        if runtime is None:
            runtime = inst['runtime']
        assert inst['runtime'] == runtime
        if nsamples is None:
            nsamples = inst['samples']
        assert inst['samples'] == nsamples

    for app in experiment['apps'].values():
        if not 'loadgen' in app:
            continue
        for sample in app['loadgen']:
            latd = sample['latencies']
            sample['min'] = min(latd[0].keys()) if latd[0] else 0
            sample['max'] = max(latd[0].keys()) if latd[0] else 0
            sample['p50'] = percentile(latd, 0.5)
            sample['p75'] = percentile(latd, 0.75)
            sample['p90'] = percentile(latd, 0.9)
            sample['p99'] = percentile(latd, 0.99)
            sample['p999'] = percentile(latd, 0.999)
            sample['p9999'] = percentile(latd, 0.9999)
            sample['count'] = sum([latd[0][k]
                                   for k in latd[0]])  # + latd[1]#dropped
            sample['dropped'] = latd[1]
            if 'tracepoints' in sample:
                sample['tracepoints'] = list(sample['tracepoints'])
            del sample['latencies']

    experiment['nsamples'] = nsamples
    experiment['runtime'] = runtime
    experiment['sample_starts'] = sample_starts
    if sample_starts_tsc:
        experiment['sample_starts_tsc'] = sample_starts_tsc


def parse_dir(dirname):
    files = os.listdir(dirname)
    assert "config.json" in files
    with open(dirname + "/config.json") as f:
        experiment = json.loads(f.read())

    experiment['apps'] = {}
    experiment['loadgens'] = []
    for host in experiment['hosts']:
        for i in range(len(experiment['hosts'][host]['apps'])):
            app = experiment['hosts'][host]['apps'][i]
            assert app['host'] == host
            if "runtime-client" in app['args']:
                experiment['loadgens'].append(app)
            elif "local-client" in app['args']:
                experiment['loadgens'].append(app)
                experiment['apps'][app['name']] = app
            else:
                experiment['apps'][app['name']] = app
            app['system'] = app.get('system', experiment['system'])
        del experiment['hosts'][host]['apps']

    load_loadgen_results(experiment, dirname)
 
    start_time = experiment['sample_starts'][0]

    for app in experiment['apps'].values():
        app['output'] = load_shm_query(experiment, app, dirname)

    for appn in experiment['apps'].keys()[:]:
        if appn.endswith("shm_query"):
            realapp = appn.split("_shm_query")[0]
            experiment['apps'][realapp]['output'] = experiment['apps'][appn]['output']
            del experiment['apps'][appn]
 
    return experiment


def arrange_2d_results(experiment):
    header1 = ["system", "name", "transport", "spin", "threads"]
    header2 = ["offered", "achieved", "min", "max", "p50", "p90",
               "p99", "p999", "p9999", "distribution", "count", "dropped"]
    # , "totalcpu"] # "totaloffered", "totalachieved",
    header3 = ["tput", "baseline", "totalcpu", "totalmembw"]
    header = header1 + header2 + header3
    lines = [header]
    # ncons = 0 # todo.

    hostname = experiment['apps'][sorted(experiment['apps'].keys())[0]]['host']

    for i, time_point in enumerate(experiment['sample_starts']):
        totalcpu = "NA"  # experiment['mpstat'][hostname][i]
        # experiment['pcmmemory'][hostname]["Memory (MB/s)"][i] if experiment['pcmmemory'][hostname] else 0
        totalmembw = "NA"
        for app_name in sorted(experiment['apps'].keys()):
            app = experiment['apps'][app_name]
            out = [app.get(k) for k in header1]
            if app.get('loadgen'):
                out += [app['loadgen'][i][k] for k in header2]
            else:
                out += [0] * len(header2)
            if app.get('output'):
                out += [app['output']['w_datapoints'][i],
                        app['output']['recorded_baseline']]
            else:
                out += [0, 0]
            out.append(totalcpu)
            out.append(totalmembw)
            lines.append(out)
    return lines


def rotate(output_lines):
    resdict = {}
    headers = output_lines[0]
    for i, h in enumerate(headers):
        resdict[h] = [l[i] for l in output_lines[1:]]
    return resdict

def do_it_all(dirname):

    filesin = os.listdir(dirname)
    found_subdirectories = False
    for file in filesin:
        if "mpps" in file:
            found_subdirectories = True
            do_it_all(dirname + "/" + file)
    if found_subdirectories:
        return

    STAT_F = "{}/stats/".format(dirname)
    RES_F = STAT_F + "results.json"
    if not os.access(RES_F, os.F_OK):
        exp = parse_dir(dirname)
        os.system("mkdir -p " + STAT_F)
        with open(RES_F, "w") as f:
            f.write(json.dumps(exp))
    else:
        with open(RES_F) as f:
            exp = json.loads(f.read())

    stats = arrange_2d_results(exp)
    bycol = rotate(stats)

    maxsz = [max(len(str(l)) for l in bycol[x] + [x]) for x in stats[0]]

    def padded(x, l): return str(x)  # + " " * (l - len(str(x)))
    with open(STAT_F + "stat.csv", "w") as f:
        for line in stats:
            x = ",".join([padded(x, maxsz[i]) for i, x in enumerate(line)])
            print(x)
            f.write(x + '\n')

    return bycol


def main():
    nfiles = len(sys.argv) - 1
    if nfiles > 1:
        from multiprocessing import Pool, cpu_count
        p = Pool(min(cpu_count(), nfiles))
        p.imap_unordered(do_it_all, sys.argv[1:])
        p.close()
        p.join()
    else:
        for d in sys.argv[1:]:
            do_it_all(d)

if __name__ == '__main__':
    main()
