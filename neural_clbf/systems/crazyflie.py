"""Define a dymamical system for Crazyflies"""
from typing import Tuple, Optional, List

import torch
import numpy as np

from .control_affine_system import ControlAffineSystem
from neural_clbf.systems.utils import Scenario, ScenarioList

#TODO @Dylan pull locally on terminal and run checks for formatting for both this
#file and the crazyflie training file

class Crazyflie(ControlAffineSystem):
    """
    Represents a quadcopter in 3D space, the crazyflie.
    The system has state
        p = [x, y, z, vx, vy, vz]
    representing the x,y,z positions and velocities of the crazyflie
    and it has control inputs
        u = [f, theta, phi, psi]
    representing the desired roll, pitch, yaw, and net rotor thrust
    
    phi = rotation about x axis
    theta = rotation about y axis
    psi = rotation about z axis
    
    The system is parameterized by
        m: mass
        
    Note: z is positive upwards
    """

    # Number of states and controls
    N_DIMS = 6
    N_CONTROLS = 4

    # State indices
    X = 0
    Y = 1
    Z = 2
    
    VX = 3
    VY = 4
    VZ = 5
    
    # Control indices
    F = 0
    PHI = 1
    THETA = 2
    PSI = 3

    def __init__(
        self,
        nominal_params: Scenario,
        dt: float = 0.01,
        controller_dt: Optional[float] = None,
        scenarios: Optional[ScenarioList] = None,
    ):
        """
        Initialize the Crazyflie.
        args:
            nominal_params: a dictionary giving the parameter values for the system.
                            Requires keys ["m"]
            dt: the timestep to use for the simulation
            controller_dt: the timestep for the LQR discretization. Defaults to dt
        raises:
            ValueError if nominal_params are not valid for this system
        """
        super().__init__(
            nominal_params, dt=dt, controller_dt=controller_dt, scenarios=scenarios,
        )

    def validate_params(self, params: Scenario) -> bool:
        """Check if a given set of parameters is valid
        args:
            params: a dictionary giving the parameter values for the system.
                    Requires keys ["m"]
        returns:
            True if parameters are valid, False otherwise
        """
        valid = True
        
        # Make sure all needed parameters were provided
        valid = valid and "m" in params

        # Make sure all parameters are physically valid
        valid = valid and params["m"] > 0

        return valid

    @property
    def n_dims(self) -> int:
        return Crazyflie.N_DIMS
    
    @property
    def angle_dims(self) -> List[int]:
        return []

    @property
    def n_controls(self) -> int:
        return Crazyflie.N_CONTROLS

    @property
    def state_limits(self) -> Tuple[torch.Tensor, torch.Tensor]:  
        """
        Return a tuple (upper, lower) describing the expected range of states for this
        system
        """
        # define upper and lower limits based around the nominal equilibrium input
        upper_limit = torch.ones(self.n_dims)
        
        #TODO @dylan test these empirically once we get controllers implemented
        upper_limit[Crazyflie.X] = 4.0
        upper_limit[Crazyflie.Y] = 4.0
        upper_limit[Crazyflie.Z] = 4.0
        upper_limit[Crazyflie.VX] = 8.0
        upper_limit[Crazyflie.VY] = 8.0
        upper_limit[Crazyflie.VZ] = 8.0

        lower_limit = -1.0 * upper_limit
        lower_limit[Crazyflie.Z] = 0

        return (upper_limit, lower_limit)

    @property
    def control_limits(self) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Return a tuple (upper, lower) describing the range of allowable control
        limits for this system
        """
        # define upper and lower limits based around the nominal equilibrium input
        # TODO @dylan these are relaxed for now, but eventually
        # these values should be measured on the hardware.
        
        # upper limits: force, phi, theta, psi
        # set psi limit to 2*pi from pi/2, may cause issues
        upper_limit = torch.tensor([100, np.pi/2, np.pi/2, 2*np.pi])
        lower_limit = -1.0 * upper_limit

        return (upper_limit, lower_limit)

    def safe_mask(self, x):
        """Return the mask of x indicating safe regions for the obstacle task
        args:
            x: a tensor of points in the state space
        """
        # We have a floor that we need to avoid and a radius we need to stay inside of
        safe_z_floor = 0.3
        safe_z_ceiling = 4.0
        
        #TODO @dylan find empirically a good value for safe_radius
        safe_radius = 4
        
        # note that direction of gravity is positive, so all points above the ground have negative z component
        safe_mask = torch.logical_and(
            x[:, Crazyflie.Z] <= safe_z_ceiling, x[:, Crazyflie.Z] >= safe_z_floor, x.norm(dim=-1) <= safe_radius
        )

        return safe_mask

    def unsafe_mask(self, x):
        """Return the mask of x indicating unsafe regions for the obstacle task
        args:
            x: a tensor of points in the state space
        """
        # We have a floor that we need to avoid and a radius we need to stay inside of
        unsafe_z_floor = 0.3
        unsafe_z_ceiling = 4.0
        unsafe_radius = 3.5
        
        unsafe_mask = torch.logical_or(
            x[:, Crazyflie.Z] < unsafe_z_floor, x[:, Crazyflie.Z] > unsafe_z_ceiling, x.norm(dim=-1) > unsafe_radius
        )

    def distance_to_goal(self, x: torch.Tensor) -> torch.Tensor:
        """Return the distance from each point in x to the goal (positive for points
        outside the goal, negative for points inside the goal), normalized by the state
        limits.
        args:
            x: the points from which we calculate distance
        """
        # probably don't need this function, may be deprecated eventually
        upper_limit, _ = self.state_limits
        return x.norm(dim=-1) / upper_limit.norm()

    def goal_mask(self, x):
        """Return the mask of x indicating points in the goal set
        args:
            x: a tensor of points in the state space
        """
        #TODO @dylan might need to be tweaked empirically
        goal_mask = torch.ones_like(x[:, 0], dtype=torch.bool)

        # Define the goal region as being near the goal
        near_goal = x.norm(dim=-1) <= 0.3
        goal_mask.logical_and_(near_goal)

        # The goal set has to be a subset of the safe set
        goal_mask.logical_and_(self.safe_mask(x))

        return goal_mask

    def _f(self, x: torch.Tensor, params: Scenario):
        """
        Return the control-independent part of the control-affine dynamics.
        args:
            x: bs x self.n_dims tensor of state
            params: a dictionary giving the parameter values for the system. If None,
                    default to the nominal parameters used at initialization
        returns:
            f: bs x self.n_dims x 1 tensor
        """
        # Extract batch size and set up a tensor for holding the result
        batch_size = x.shape[0]
        f = torch.zeros((batch_size, self.n_dims, 1))
        f = f.type_as(x)

        # Derivatives of positions are just velocities
        f[:, Crazyflie.X] = x[:, Crazyflie.VX]  # x
        f[:, Crazyflie.Y] = x[:, Crazyflie.VY]  # y
        f[:, Crazyflie.Z] = x[:, Crazyflie.VZ]  # z

        # Constant acceleration in z due to gravity
        f[:, Crazyflie.VZ] = -9.81

        # Orientation velocities are directly actuated

        return f

    def _g(self, x: torch.Tensor, params: Scenario):
        """
        Return the control-dependent part of the control-affine dynamics.
        args:
            x: bs x self.n_dims tensor of state
            params: a dictionary giving the parameter values for the system. If None,
                    default to the nominal parameters used at initialization
        returns:
            g: bs x self.n_dims x self.n_controls tensor
        """
        # Extract batch size and set up a tensor for holding the result
        batch_size = x.shape[0]
        g = torch.zeros((batch_size, self.n_dims, self.n_controls))
        g = g.type_as(x)

        # Extract the needed parameters
        m = params["m"]

        # Derivatives of linear velocities depend on thrust f
        s_theta = torch.sin(x[:, Crazyflie.THETA])
        c_theta = torch.cos(x[:, Crazyflie.THETA])
        s_phi = torch.sin(x[:, Crazyflie.PHI])
        c_phi = torch.cos(x[:, Crazyflie.PHI])
        g[:, Crazyflie.VX, Crazyflie.F] = s_theta / m
        g[:, Crazyflie.VY, Crazyflie.F] = -s_phi * c_theta / m
        g[:, Crazyflie.VZ, Crazuflie.F] = c_phi * c_theta / m

        
        # Derivatives of all orientations are control variables
        # g[:, Crazyflie.PHI :, Crazyflie.PHI_DOT :] = torch.eye(self.n_controls - 1)

        return g
    
    @property
    def u_eq(self):
        u_eq = torch.zeros((1, self.n_controls))
        u_eq[0, Crazyflie.F] = self.nominal_params["m"] * 9.81
        return u_eq
