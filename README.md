# Critical Raw Materials ABM: lithium toy model (v3)

An agent-based model of the lithium supply chain, built as the toy model for my PhD project on materials feasibility. Mines extract and concentrate ore or brine. A single global refinery converts concentrate into battery-grade lithium (LCE). A manufacturer turns that into a cathode-product proxy, and end use accumulates it. Exogenous IEA demand pulls material through the chain once a year. Firms decide what to offer, buy and build, and a mass-balance ledger records every tonne.

This repository mirrors the model folder of my working repository, and it is updated automatically whenever I commit there. The `02_Model/v3/` path is kept so that the notebooks find the code without any changes.

## Setup

Tested with Python 3.13.

```bash
git clone https://github.com/crowleyshawj/CriticalRawMaterialsABM.git
cd CriticalRawMaterialsABM
pip install -r 02_Model/v3/requirements.txt
jupyter lab
```

## Where to start

- `02_Model/v3/demo/demo261007.ipynb`: the meeting demonstration. Change the values under **Settings**, then *Run All*.
- `02_Model/v3/explainer/model_modules.ipynb`: a guide to each module, its key equations and its limitations.
- `02_Model/v3/demo/model_experiments.ipynb`: the working notebook for experiments.

## Layout

| Folder | Contents |
|---|---|
| `02_Model/v3/src` | The model package (`import v3.src…`) |
| `02_Model/v3/data` | Input data: mine project database, USGS production, IEA demand |
| `02_Model/v3/demo` | Runnable demonstrations and experiments |
| `02_Model/v3/explainer` | Explanatory notebooks and the assumptions register |

Codes such as `D-GLB-32` in the notebooks refer to entries in my decisions log, which is kept in the working repository and is not included here.
