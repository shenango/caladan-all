import os
import sys
from heapq import merge

if sys.version_info[0] < 3:
    raise Exception("Python 3 is required.")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

cycles_per_us = None

def readfile(f):
    WARMUP = 0
    dat = []
    with open(f) as ff:
        d = ff.read()

    is_sorted = True
    last_i = 0
    print("Reading full request trace... (may take awhile)")
    for line in d.splitlines():
        if "ticks / us" in line:
            global cycles_per_us
            cycles_per_us = int(line.split("detected")[1].split()[0])
            continue

        line = line.split("Trace: ")
        if len(line) < 2:
            continue

        for tup in line[1].split()[:-1]:
            a, b, c = tup.split(":", 2)
            if ':' in c:
                c, d = c.split(":")
            else:
                d = 0
            a, b, c = (int(a), float(b), float(c))
            if a <= 1000000 + WARMUP or b == -1:
                continue
            if c <= 0:
                c = float("inf")

            d = int(d)
            is_sorted = is_sorted and last_i <= d
            # assert is_sorted, "{} {} {}".format(last_i, d, f)
            last_i = d

            dat.append((d, a, c // 1000))

    print(len(dat))
    if is_sorted:
        return dat
    return sorted(dat)


def windower(x, y, cycles_per_us, ms_window=20, percentile=0.999):
    newx, newy, newz = [], [], []
    i = 0
    start = None
    wsize = 0
    wcnts = 0
    cycles_per_window = ms_window * 1000 * cycles_per_us
    curWinEnd = x[0] + cycles_per_window

    for i in range(len(x)):
        while x[i] > curWinEnd:
            if start is not None:
                newx.append((curWinEnd - x[0]) / (cycles_per_us * 1e6))
                ys = sorted(y[start:i])
                wsize += i - start
                wcnts += 1
                if percentile == 'max':
                    newy.append(ys[-1])
                elif percentile == 'avg':
                    newy.append(sum(ys) / len(ys) if ys else 0)
                else:
                    newy.append(ys[int(len(ys) * percentile)])
                newz.append(len(ys) * (1e3 / ms_window))
            start = None
            curWinEnd += cycles_per_window

        if start is None:
            start = i
    return newx, newy, newz

def read_mem(directory, first_tsc, last_tsc, cycles_per_us, ax):
    x, y = [], []
    with open("{}/mem.log".format(directory)) as f:
        for line in f:
            try:
                _m, mbps, tsc = line.split()
                tsc = int(tsc)
                if tsc < first_tsc or tsc > last_tsc: continue
                x.append(tsc - first_tsc)
                y.append(float(mbps))
            except:
                continue
    x, y, _z = windower(x, y, cycles_per_us, percentile='avg')
    ax.plot(x,y)
    ax.set_ylabel("Mem BW\n(MB/s)")

def parse_shmlog(arg, first_tsc, last_tsc, cycles_per_us, ax):
    xs, ys = [], []
    lastx = None
    for l in open(arg):
        try:
            ls = l.strip().split()
            hxkey = int(ls[0], 16)
            ls = list(map(int, ls[1:]))
        except Exception as e:
            continue

        if ls[-1] < first_tsc: continue
        if ls[-1] > last_tsc: continue

        ll = lastx
        lastx = ls[-1]
        if ll is None:
            continue
        xs.append(lastx - first_tsc)
        y = ls[-2]
        if y == 0.0:
            ys.append(0)
            continue
        cycles_per_op = (lastx - ll) / y
        cycles_per_s = cycles_per_us * float(1e6)
        # ops / cycle, cycles per us
        ys.append(cycles_per_s / cycles_per_op)
    assert xs, arg
    xs, ys, _z = windower(xs, ys, cycles_per_us, percentile='avg')
    lbl = arg.split("/")[-1].split("_shm_query")[0]

    max_bes = {
        'x264': 56.8336,
        'streamcluster': 926049,
        'swaptionsGC': 2326233.0 / 142.0,
        'streamDRAM': 1945.0,
    }
    ys = list(map(lambda a: a * 100.0 / max_bes[lbl], ys))
    ax.plot(xs, ys, label=lbl)
    ax.set_ylabel("BE Op/s\n(%)")
    ax.legend()

def graph_experiment_figure6(directory):
    plt.clf()
    fig = plt.figure()
    gs = fig.add_gridspec(4, 4)
    axs = [fig.add_subplot(gs[i, :4]) for i in range(4)]
    earliest_ts, latest_ts = 0, 0
    files = os.listdir(directory)
    with open("{}/memcached.out".format(directory)) as f:
        dat = f.read()
    cycles_per_us = int(dat.split("time: detected ")[1].split()[0])
    for f in files:
        if f.endswith(".memcached.out"):
            latencytrace = readfile(directory + "/" + f)
            if not latencytrace:
                continue
            tm_tsc, tm, lat = zip(*latencytrace)
            x,y,z = windower(tm_tsc, lat, cycles_per_us)
            print(len(x), len(y), len(z))
            name = f.split(".")[-2]
            axs[0].plot(x,y, label=name)
            axs[0].set_ylabel("99.9% Lat. (us)")
            axs[1].plot(x,z, label=name)
            axs[1].set_ylabel("LC\nThroughput")
            axs[1].set_ylim(0, 1.25 * max(z))
            earliest_ts = tm_tsc[0]
            latest_ts = tm_tsc[-1]
    axs[1].legend()
    axs[0].legend()
    read_mem(directory, earliest_ts, latest_ts, cycles_per_us, axs[2])
    parse_shmlog("{}/swaptionsGC_shm_query.out".format(directory), earliest_ts, latest_ts, cycles_per_us, axs[3])
    plt.xlabel("Time (s)")
    w, h = fig.get_size_inches()
    fig.set_size_inches(w*1.5, h*1.5)
    fig.tight_layout()
    plt.savefig("figure_6_caladan.pdf")

def graph_experiment_figure8(directory):
    fig = plt.figure()
    gs = fig.add_gridspec(5, 5)
    axs = [fig.add_subplot(gs[i, :5]) for i in range(5)]
    earliest_ts, latest_ts = 0, 0
    files = os.listdir(directory)
    dats = {}
    memcs = []
    for f in files:
        if f.endswith(".memcached.out"):
            memcs.append(readfile(directory + "/" + f))
        elif f.endswith(".silo.out"):
            dats['silo'] = list(zip(*readfile(directory + "/" + f)))
        elif f.endswith(".storage.out"):
            dats['storage'] = list(zip(*readfile(directory + "/" + f)))
    dats['memcached'] = list(zip(*list(merge(*memcs))))
    min_tsc = min(dats[app][0][0] for app in dats)
    max_tsc = max(dats[app][0][-1] for app in dats)
    maxs = {
        'memcached': 10.0,
        'silo': 0.5,
        'storage': 0.293979,
    }
    for i, (app, dat) in enumerate(dats.items()):
        x,y,z = windower(dat[0], dat[2], cycles_per_us)
        print(len(x), len(y), len(z))
        axs[i].plot(x,y, label=app)
        axs[i].set_ylabel("99.9% Lat. (us)")
        z = [a * 100.0 / (1e6 * maxs[app]) for a in z]
        axs[3].plot(x, z, label=app)
        axs[i].legend()
        axs[3].set_ylabel("LC\nThroughput (%)")
        axs[3].set_ylim(0, 1.25 * max(z))
    axs[3].legend()
    for be in ["swaptionsGC", "streamcluster"]:
        parse_shmlog("{}/{}_shm_query.out".format(directory, be), min_tsc, max_tsc, cycles_per_us, axs[4])
    plt.xlabel("Time (s)")
    w, h = fig.get_size_inches()
    fig.set_size_inches(w*1.5, h*1.5)
    fig.tight_layout()
    plt.savefig("figure_8_multiapp.pdf")



