from copy import copy
import torch

from neural_clbf.systems import STCar
from neural_clbf.controllers import NeuralCLBFController
from neural_clbf.experiments.common.episodic_datamodule import (
    EpisodicDataModule,
)

# Import the plotting callbacks, which seem to be needed to load from the checkpoint
from neural_clbf.experiments.train_single_track_car import (  # noqa
    rollout_plotting_cb,  # noqa
    clbf_plotting_cb,  # noqa
)

from neural_clbf.experiments.data_generation.stcar_s_curve_rollout import (
    save_stcar_s_curve_rollout,
)


def doMain():
    checkpoint_file = "saved_models/good/stcar/f6473d0_v0.ckpt"

    controller_period = 0.01
    simulation_dt = 0.001

    # Define the dynamics model
    nominal_params = {
        "psi_ref": 1.0,
        "v_ref": 10.0,
        "a_ref": 0.0,
        "omega_ref": 0.0,
    }
    stcar = STCar(nominal_params, dt=simulation_dt, controller_dt=controller_period)

    # Initialize the DataModule
    initial_conditions = [
        (-0.1, 0.1),  # sxe
        (-0.1, 0.1),  # sye
        (-0.1, 0.1),  # delta
        (-0.1, 0.1),  # ve
        (-0.1, 0.1),  # psi_e
        (-0.1, 0.1),  # psi_dot
        (-0.1, 0.1),  # beta
    ]

    # Define the scenarios
    scenarios = []
    omega_ref_vals = [-1.5, 1.5]
    for omega_ref in omega_ref_vals:
        s = copy(nominal_params)
        s["omega_ref"] = omega_ref

        scenarios.append(s)

    data_module = EpisodicDataModule(
        stcar,
        initial_conditions,
        trajectories_per_episode=1,
        trajectory_length=10,
        fixed_samples=100,
        max_points=5000000,
        val_split=0.1,
        batch_size=64,
    )

    clbf_controller = NeuralCLBFController.load_from_checkpoint(
        checkpoint_file,
        map_location=torch.device("cpu"),
        dynamics_model=stcar,
        scenarios=scenarios,
        datamodule=data_module,
        clbf_hidden_layers=2,
        clbf_hidden_size=64,
        u_nn_hidden_layers=2,
        u_nn_hidden_size=64,
        clbf_lambda=0.1,
        safety_level=1.0,
        controller_period=controller_period,
        clbf_relaxation_penalty=1e8,
        primal_learning_rate=1e-3,
        penalty_scheduling_rate=0,
        num_init_epochs=11,
        optimizer_alternate_epochs=1,
        epochs_per_episode=200,
        use_nominal_in_qp=False,
    )

    save_stcar_s_curve_rollout(
        clbf_controller, "rCLBF-QP", controller_period, stcar, randomize_path=True
    )


if __name__ == "__main__":
    doMain()
