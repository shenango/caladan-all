import pandas as pd
import os, sys
import json

import summary

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig = plt.figure()

def read_file(file):
    out = {}
    subdirs = os.listdir(file)
    for sd in subdirs:
        if "mpps" in sd:
            out.update(read_file(file + "/" + sd))
    try:
        with open(file + "/stats/results.json") as f:
            exp = json.loads(f.read())
    except:
        if out: return out
        raise
    lc_apps = []
    be_apps = []
    hosts = set()
    for app in exp['apps'].values():
        if 'loadgen' in app:
            lc_apps.append(app)
            if app['host'] not in hosts:
                hosts.add(app['host'])
        if app['output'] is not None and app not in be_apps:
            be_apps.append(app)
    exp['lc_apps'] = lc_apps
    exp['be_apps'] = be_apps
    exp['lc_hosts'] = list(hosts)
    out[file] = exp
    return out

def fs_to_dataframe(fs):
    frames = []
    for f in fs:
        if not fs[f]:
            subdirs = os.listdir(f)
            if any("mpps" in x for x in subdirs):
                continue
        assert fs[f], f
        lc_app = fs[f]['lc_apps'][0]
        be_app = fs[f]['be_apps'][0] if fs[f]['be_apps'] else None

        f1 = {}

        assert len(fs[f]['lc_hosts']) == 1
        host = fs[f]['lc_hosts'][0]

        loadgen_keys = lc_app['loadgen'][0].keys()
        for key in loadgen_keys:
            if key == 'time_tsc': continue
            f1[key] = [lc_app['loadgen'][i][key] for i in range(len(lc_app['loadgen']))]

        f1['sample_order'] = [i for i in range(len(f1['p999']))]
        f1['lc_name'] = [lc_app['name']] * len(f1['achieved'])
        f1['lc_cores'] = [lc_app['threads']] * len(f1['achieved'])
        f1['lc_name'] = [lc_app['name']] * len(f1['achieved'])
        f1['transport'] = [lc_app['transport']] * len(f1['achieved'])
        f1['lc_app'] = [lc_app['app']] * len(f1['achieved'])

        if be_app and be_app.get('output'):
            f1['bg'] = be_app['output']['w_datapoints']

        for k in list(f1.keys()):
            if not f1[k]:
                del f1[k]

        npoints = min(len(f1[k]) for k in f1)

        f1['fname'] = [f] * npoints
        if 'mpps' in f:
          ll = float(f.split("/")[-1].split("mpps")[0])
          f1['mppstarget'] = [ll] * npoints
        tag = fs[f].get('group_tag', fs[f]['name'])
        f1['tag'] = [tag] * npoints

        be_name = be_app['name'] if be_app else "No BE"
        be_name = be_name.split("_shm_query")[0]
        f1['be_name'] = [be_name] * npoints

        for k in f1:
            f1[k] = f1[k][:npoints]

        frames.append(pd.DataFrame.from_dict(f1))

    return pd.concat(frames)

def graph_lc_combos(fs):
    if not fs: return
    plt.clf()
    result = fs_to_dataframe(fs)


    lcs = ['storage_service', 'memcached', 'silo']

    fig, axs = plt.subplots(nrows=2, ncols=len(lcs))

    max_bes = {
        'x264': 56.8336,
        'streamcluster': 926049,
        'swaptionsGC': 2326233.0 / 142.0,
        'streamDRAM': 5840.631460038528,
        'streamL2': 50161.1099851102,
    }

    for i, l in enumerate(lcs):
        rs = result[result.lc_app == l]

        for be in ['x264', 'streamcluster', 'swaptionsGC', 'streamL2', 'streamDRAM', 'No BE']:
            bs = rs[rs.be_name == be]
            for h, r in bs.groupby('tag'):
                s = set(r['sample_order'])
                assert len(s) == 1 or len(s) == len(r)
                if len(s) == 1:
                    r = r.sort_values('mppstarget')
                axs[0][i].set_title(l)
                label = h.split("-", 2)[-1]
                bename = r['be_name'].iloc[0]

                axs[0][i].plot(r['achieved'], r['p999'], label=bename)

                max_achieved = max(r['achieved'])
                maxidx = len(r['achieved'])
                for ii, v in enumerate(r['achieved']):
                    if v == max_achieved:
                        maxidx = ii + 1
                        break
                if bename != "No BE":
                    maxbe = max_bes[bename]
                    bg_normalized = list(map(lambda x : 100 * x / maxbe, r['bg']))
                    axs[1][i].plot(r['achieved'][:maxidx], bg_normalized[:maxidx], label=bename)
                else:
                    bg_normalized = [0]*len(r['achieved'])

    axs[0][0].set_ylabel("p999")
    for i, ax in enumerate(axs[0]):
        ax.legend()
        if i != 1:
            ax.set_ylim(0,800)
        if i == 1:
            ax.set_ylim(0, 300)
    for ax in axs[1]:
        ax.legend()
        ax.set_ylim(0, 100)


    fig.set_size_inches(12, 6)
    fig.tight_layout()
    plt.savefig('lcs_combos.pdf')

def graph_9b(fs):
    plt.clf()
    lines = 0
    for file in fs:
        if "figure_9b" not in file: continue
        if "-spinning" in file:
            name = "pinned"
        elif "ksched" in file:
            name = "ksched"
        df = fs_to_dataframe({file: fs[file]})
        plt.plot(df['achieved'], df['p999'], label=name)
        lines += 1
    if not lines: return
    plt.ylim(0, 1000)
    plt.legend()
    plt.ylabel("99.9th% (us)")
    plt.xlabel("RPS")
    plt.savefig("figure_9b.pdf")

def graph_9c(fs):
    plt.clf()
    lines = 0
    for file in fs:
        if "figure_9c" not in file: continue
        name = file.split("figure_9c_")[1].replace("_", " ")
        df = fs_to_dataframe({file: fs[file]})
        print(name)
        plt.plot(df['achieved'], df['p999'], label=name)
        lines += 1
    if not lines: return
    plt.ylim(0, 1500)
    plt.legend()
    plt.ylabel("99.9th% (us)")
    plt.xlabel("RPS")
    plt.savefig("figure_9c.pdf")

def main():
    fs = {}
    for f in sys.argv[1:]:
        if "memcached_trace" in f:
            import graph_timeseries
            graph_timeseries.graph_experiment_figure6(f)
            continue
        elif "multi" in f:
            import graph_timeseries
            graph_timeseries.graph_experiment_figure8(f)
            continue
        else:
            summary.do_it_all(f)
        fs.update(read_file(f))
    graph_lc_combos({f: fs[f] for f in fs if "figure_7" in f})
    graph_9b(fs)
    graph_9c(fs)

if __name__ == '__main__':
    main()