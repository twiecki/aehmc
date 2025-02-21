from typing import Callable, Tuple

import aesara.tensor as aet
import numpy as np
from aesara.tensor.random.utils import RandomStream
from aesara.tensor.var import TensorVariable

from aehmc.integrators import IntegratorStateType

ProposalStateType = Tuple[
    IntegratorStateType, TensorVariable, TensorVariable, TensorVariable
]


def proposal_generator(kinetic_energy: Callable, divergence_threshold: float):
    def update(initial_energy, state):
        """Generate a new proposal from a trajectory state.

        The trajectory state records information about the position in the state
        space and corresponding potential energy. A proposal also carries a
        weight that is equal to the difference between the current energy and
        the previous one. It thus carries information about the previous state
        as well as the current state.

        Parameters
        ----------
        initial_energy:
            The initial energy.
        state:
            The new state.

        Return
        ------
        A tuple that contains the new proposal and a boolean that indicates
        whether the current transition is divergent.

        """
        q, p, potential_energy, _ = state
        new_energy = potential_energy + kinetic_energy(p)

        delta_energy = initial_energy - new_energy
        delta_energy = aet.where(aet.isnan(delta_energy), -np.inf, delta_energy)
        is_transition_divergent = aet.abs_(delta_energy) > divergence_threshold

        weight = delta_energy
        p_accept = aet.clip(aet.exp(delta_energy), 0.0, 1.0)

        return (state, new_energy, weight, p_accept), is_transition_divergent

    return update


# -------------------------------------------------------------------
#                     PROGRESSIVE SAMPLING
# -------------------------------------------------------------------


def progressive_uniform_sampling(
    srng: RandomStream, proposal: ProposalStateType, new_proposal: ProposalStateType
) -> ProposalStateType:
    """Uniform proposal sampling.

    Choose between the current proposal and the proposal built from the last
    trajectory state.

    Parameters
    ----------
    srng
        RandomStream object
    proposal
        The current proposal, it does not necessarily correspond to the
        previous state on the trajectory
    new_proposal
        The proposal built from the last trajectory state.

    Return
    ------
    Either the current or the new proposal.

    """
    state, energy, weight, _ = proposal
    new_state, new_energy, new_weight, _ = new_proposal

    p_accept = aet.expit(new_weight - weight)
    do_accept = srng.bernoulli(p_accept)
    updated_proposal = maybe_update_proposal(do_accept, proposal, new_proposal)

    return updated_proposal


def progressive_biased_sampling(
    srng: RandomStream, proposal: ProposalStateType, new_proposal: ProposalStateType
) -> ProposalStateType:
    """Baised proposal sampling.

    Choose between the current proposal and the proposal built from the last
    trajectory state. Unlike uniform sampling, biased sampling favors new
    proposals. It thus biases the transition away from the trajectory's initial
    state.

    Parameters
    ----------
    srng
        RandomStream object
    proposal
        The current proposal, it does not necessarily correspond to the
        previous state on the trajectory
    new_proposal
        The proposal built from the last trajectory state.

    Return
    ------
    Either the current or the new proposal.

    """
    state, energy, weight, _ = proposal
    new_state, new_energy, new_weight, _ = new_proposal

    p_accept = aet.clip(aet.exp(new_weight - weight), 0.0, 1.0)
    do_accept = srng.bernoulli(p_accept)
    updated_proposal = maybe_update_proposal(do_accept, proposal, new_proposal)

    return updated_proposal


def maybe_update_proposal(
    do_accept: bool, proposal: ProposalStateType, new_proposal: ProposalStateType
) -> ProposalStateType:
    """Return either proposal depending on the boolean `do_accept`"""
    state, energy, weight, sum_p_accept = proposal
    new_state, new_energy, new_weight, new_sum_p_accept = new_proposal

    updated_weight = aet.logaddexp(weight, new_weight)
    updated_sum_p_accept = sum_p_accept + new_sum_p_accept

    updated_q = aet.where(do_accept, new_state[0], state[0])
    updated_p = aet.where(do_accept, new_state[1], state[1])
    updated_potential_energy = aet.where(do_accept, new_state[2], state[2])
    updated_potential_energy_grad = aet.where(do_accept, new_state[3], state[3])
    updated_energy = aet.where(do_accept, new_energy, energy)

    return (
        (updated_q, updated_p, updated_potential_energy, updated_potential_energy_grad),
        updated_energy,
        updated_weight,
        updated_sum_p_accept,
    )
