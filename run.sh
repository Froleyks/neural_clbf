eval "$(~/miniforge3/bin/conda shell.zsh hook)"
conda create --name clbf21 python=3.9
conda activate clbf21
pip install -e .
pip install -r requirements.txt
