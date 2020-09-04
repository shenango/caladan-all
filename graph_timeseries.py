import os
import sys

if sys.version_info[0] < 3:
    raise Exception("Python 3 is required.")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig = plt.figure()

gs = fig.add_gridspec(4, 4)
axs = [fig.add_subplot(gs[i, :4]) for i in range(4)]

def readfile(f):
    WARMUP = 0
    dat = []
    with open(f) as ff:
        d = ff.read()

    is_sorted = True
    last_i = 0
    for line in d.splitlines():
        line = line.split("Trace: ")
        if len(line) < 2:
            continue

        print("Reading latencies... (may take awhile)")
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
            assert is_sorted
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

def read_mem(directory, first_tsc, last_tsc, cycles_per_us):
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
    axs[2].plot(x,y)
    axs[2].set_ylabel("Mem BW\n(MB/s)")

def parse_shmlog(arg, first_tsc, last_tsc, cycles_per_us):
    xs, ys = [], []
    lastx = None
    for l in open(arg):
        try:
            ls = list(map(int, l.strip().split()))
        except:
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
    xs, ys, _z = windower(xs, ys, cycles_per_us, percentile='avg')
    axs[3].plot(xs, ys)
    axs[3].set_ylabel("BE Tput\n(Op/s)")


def graph_experiment(directory):
    earliest_ts, latest_ts = 0, 0
    files = os.listdir(directory)
    with open("{}/memcached.out".format(directory)) as f:
        dat = f.read()
    cycles_per_us = int(dat.split("time: detected ")[1].split()[0])
    for f in files:
        if f.endswith(".out"):
            latencytrace = readfile(directory + "/" + f)
            if not latencytrace:
                continue
            tm_tsc, tm, lat = zip(*latencytrace)
            x,y,z = windower(tm_tsc, lat, cycles_per_us)
            print(len(x), len(y), len(z))
            axs[0].plot(x,y)
            axs[0].set_ylabel("99.9% Lat. (us)")
            axs[1].plot(x,z)
            axs[1].set_ylabel("LC\nThroughput")
            axs[1].set_ylim(0, 1.25 * max(z))
            earliest_ts = tm_tsc[0]
            latest_ts = tm_tsc[-1]
    read_mem(directory, earliest_ts, latest_ts, cycles_per_us)
    parse_shmlog("{}/swaptions_shm_query.out".format(directory), earliest_ts, latest_ts, cycles_per_us)
    plt.xlabel("Time (s)")
    w, h = fig.get_size_inches()
    fig.set_size_inches(w*1.5, h*1.5)
    fig.tight_layout()
    plt.savefig("caladan_timeseries_experiment.pdf")


if __name__ == '__main__':
    graph_experiment(sys.argv[1])
