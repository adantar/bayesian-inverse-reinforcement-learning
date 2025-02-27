import numpy as np
from numpy import inf
import sparse
import time

def fast_softmax(x, t=1):
    assert t>=0
    if len(x.shape) == 1: x = x.reshape((1,-1))
    if t == 0: return np.amax(x, axis=1)
    if x.shape[1] == 1: return x

    x_max = x.max(axis=1).reshape(-1, 1)
    
    sm = t * np.log(np.exp((x - x_max) / t).sum(axis=1, keepdims=True)) + x_max

    return sm.flatten()

def softmax(x, t=1):
    '''
    Numerically stable computation of t*log(\sum_j^n exp(x_j / t))
    
    If the input is a 1D numpy array, computes it's softmax: 
        output = t*log(\sum_j^n exp(x_j / t)).
    If the input is a 2D numpy array, computes the softmax of each of the rows:
        output_i = t*log(\sum_j^n exp(x_{ij} / t))
    
    Parameters
    ----------
    x : 1D or 2D numpy array
        
    Returns
    -------
    1D numpy array 
        shape = (n,), where: 
            n = 1 if x was 1D, or 
            n is the number of rows (=x.shape[0]) if x was 2D.
    '''
    assert t>=0
    if len(x.shape) == 1: x = x.reshape((1,-1))
    if t == 0: return np.amax(x, axis=1)
    if x.shape[1] == 1: return x
    # t = 1
   
    def softmax_2_arg(x1,x2, t):
        ''' 
        Numerically stable computation of t*log(exp(x1/t) + exp(x2/t))
        
        Parameters
        ----------
        x1 : numpy array of shape (n,1)
        x2 : numpy array of shape (n,1)
        
        Returns
        -------
        numpy array of shape (n,1)
            Each output_i = t*log(exp(x1_i / t) + exp(x2_i / t))
        '''
        tlog = lambda x: t * np.log(x)
        expt = lambda x: np.exp(x/t)
                
        max_x = np.amax((x1,x2),axis=0)
        min_x = np.amin((x1,x2),axis=0)    
        return max_x + tlog(1+expt((min_x - max_x)))
    
    sm = softmax_2_arg(x[:,0],x[:,1], t)
    # Use the following property of softmax_2_arg:
    # softmax_2_arg(softmax_2_arg(x1,x2),x3) = log(exp(x1) + exp(x2) + exp(x3))
    # which is true since
    # log(exp(log(exp(x1) + exp(x2))) + exp(x3)) = log(exp(x1) + exp(x2) + exp(x3))
    for (i, x_i) in enumerate(x.T):
        if i>1: sm = softmax_2_arg(sm, x_i, t)
    return sm

def vi_boltzmann(mdp, gamma, r_s, r_a, horizon=None,  temperature=1, 
                            threshold=1e-16):
    '''
    Finds the optimal state and state-action value functions via value 
    iteration with the "soft" max-ent Bellman backup:
    
    Q_{sa} = r_s + gamma * \sum_{s'} p(s'|s,a)V_{s'}
    V'_s = temperature * log(\sum_a exp(Q_{sa}/temperature))
    Computes the Boltzmann rational policy 
    \pi_{s,a} = exp((Q_{s,a} - V_s)/temperature).
    
    Parameters
    ----------
    mdp : object
        Instance of the MDP class.
    gamma : float 
        Discount factor; 0<=gamma<=1.
    r : 1D numpy array
        Initial reward vector with the length equal to the 
        number of states in the MDP.
    horizon : int
        Horizon for the finite horizon version of value iteration.
    threshold : float
        Convergence threshold.
    Returns
    -------
    1D numpy array
        Array of shape (mdp.nS, 1), each V[s] is the value of state s under 
        the reward r and Boltzmann policy.
    2D numpy array
        Array of shape (mdp.nS, mdp.nA), each Q[s,a] is the value of 
        state-action pair [s,a] under the reward r and Boltzmann policy.
    2D numpy array
        Array of shape (mdp.nS, mdp.nA), each value p[s,a] is the probability 
        of taking action a in state s.
    '''
    
    # No rewards for state-action pairs where there is no transition
    mask_Q = mdp.valid_sa
    # No rewards for END state
    mask_V = mdp.valid_s
        
    #Value iteration   
    V = np.copy(r_s)
    t = 0
    diff = float("inf")
    while diff > threshold:
#         print(diff)
        V_prev = np.copy(V)

        # ∀ s,a: Q[s,a] = (r_s + gamma * \sum_{s'} p(s'|s,a)V_{s'})
        Q = np.multiply(
            r_s.reshape(-1, 1) 
            + r_a.reshape(1, -1) 
            + gamma * sparse.dot(mdp.T, V_prev)
            , mask_Q
            )

        # ∀ s: V_s = temperature * log(\sum_a exp(Q_sa/temperature))
        # V = softmax(Q, temperature) * mask_V
        V = fast_softmax(Q, temperature) * mask_V

        diff = np.amax(abs(V_prev - V))
        
        t+=1
        if t<horizon and gamma==1:
            # When \gamma=1, the backup operator is equivariant under adding 
            # a constant to all entries of V, so we can translate min(V) 
            # to be 0 at each step of the softmax value iteration without 
            # changing the policy it converges to, and this fixes the problem 
            # where log(nA) keep getting added at each iteration.
            V = V - np.amin(V)
        if horizon is not None:
            if t == horizon: break
    
    V = V.reshape((-1, 1))
        
    # Compute policy
    expt = lambda x: np.exp(x/temperature)
    tlog = lambda x: temperature * np.log(x)

    # ∀ s,a: policy_{s,a} = exp((Q_{s,a} - V_s)/t)
    policy = expt(Q - V) * mdp.valid_sa
    #########################
#     policy = np.exp((Q)/temperature) * mdp.valid_sa
    policy /= policy.sum(axis=1).reshape(-1,1)
    #########################
        
    return V, Q, policy

def compute_s_a_visitations(mdp, gamma, trajectories):
    '''
    Given a list of trajectories in an mdp, computes the state-action 
    visitation counts and the probability of a trajectory starting in state s.
    
    State-action visitation counts:
    sa_visit_count[s,a] = \sum_{i,t} 1_{traj_s_{i,t} = s AND traj_a_{i,t} = a}
    P_0(s) -- probability that the trajectory will start in state s. 
    P_0[s] = \sum_{i,t} 1_{t = 0 AND traj_s_{i,t} = s}  / i
    P_0 is used in computing the occupancy measure of the MDP.
    Parameters
    ----------
    mdp : object
        Instance of the MDP class.
    gamma : float 
        Discount factor; 0<=gamma<=1.
    trajectories : 3D numpy array
        Expert trajectories. 
        Dimensions: [number of traj, timesteps in the traj, 2: state & action].
    Returns
    -------
    (2D numpy array, 1D numpy array)
        Arrays of shape (mdp.nS, mdp.nA) and (mdp.nS).
    '''

    s_0_count = np.zeros(mdp.nS)
    sa_visit_count = np.zeros((mdp.nS, mdp.nA+1))
    
    for traj in trajectories:
        # traj[0][0] is the state of the first timestep of the trajectory.
        s_0_count[traj[0][0]] += 1
        for (s, a) in traj:
            if a>=0:
                sa_visit_count[s, a] += 1
            else:
                sa_visit_count[s, -1] += 1
      
    # Count into probability        
    P_0 = s_0_count / trajectories.shape[0]
    
    return sa_visit_count, P_0

def compute_D(mdp, gamma, policy, P_0=None, t_max=None, threshold=1e-6):
    '''
    Computes occupancy measure of a MDP under a given time-constrained policy 
    -- the expected discounted number of times that policy π visits state s in 
    a given number of timesteps.
    
    The version w/o discount is described in Algorithm 9.3 of Ziebart's thesis: 
    http://www.cs.cmu.edu/~bziebart/publications/thesis-bziebart.pdf.
    
    The discounted version can be found in the supplement to Levine's 
    "Nonlinear Inverse Reinforcement Learning with Gaussian Processes" (GPIRL):
    https://graphics.stanford.edu/projects/gpirl/gpirl_supplement.pdf.
    Parameters
    ----------
    mdp : object
        Instance of the MDP class.
    gamma : float 
        Discount factor; 0<=gamma<=1.
    policy : 2D numpy array
        policy[s,a] is the probability of taking action a in state s.
    P_0 : 1D numpy array of shape (mdp.nS)
        i-th element is the probability that the traj will start in state i.
    t_max : int
        number of timesteps the policy is executed.
    Returns
    -------
    1D numpy array of shape (mdp.nS)
    '''

    if P_0 is None: P_0 = np.ones(mdp.nS) / mdp.nS
    D_prev = np.zeros_like(P_0)     
    
    t = 0
    diff = float("inf")
    while diff > threshold:
#         print(diff)
        
        # ∀ s: D[s] <- P_0[s]
        D = np.copy(P_0)

        for s in range(mdp.nS):
            for a in range(mdp.nA):
                # for all s_prime reachable from s by taking a do:
                for p_sprime, s_prime, _ in mdp.P[s][a]:
                    D[s_prime] += gamma * D_prev[s] * policy[s, a] * p_sprime

        diff = np.amax(abs(D_prev - D))    
        D_prev = np.copy(D)
        
        if t_max is not None:
            t+=1
            if t==t_max: break
    
    return D

def max_causal_ent_irl(mdp, feature_matrix, trajectories, gamma=1, h=None, 
                       temperature=1e-2, epochs=300, learning_rate=0.01, theta=None):
    '''
    Finds theta, a reward parametrization vector (r[s] = features[s]'.*theta) 
    that maximizes the log likelihood of the given expert trajectories, 
    modelling the expert as a Boltzmann rational agent with given temperature. 
    
    This is equivalent to finding a reward parametrization vector giving rise 
    to a reward vector giving rise to Boltzmann rational policy whose expected 
    feature count matches the average feature count of the given expert 
    trajectories (Levine et al, supplement to the GPIRL paper).
    Parameters
    ----------
    mdp : object
        Instance of the MDP class.
    feature_matrix : 2D numpy array
        Each of the rows of the feature matrix is a vector of features of the 
        corresponding state of the MDP. 
    trajectories : 3D numpy array
        Expert trajectories. 
        Dimensions: [number of traj, timesteps in the traj, state and action].
    gamma : float 
        Discount factor; 0<=gamma<=1.
    h : int
        Horizon for the finite horizon version of value iteration.
    temperature : float >= 0
        The temperature parameter for computing V, Q and policy of the 
        Boltzmann rational agent: p(a|s) is proportional to exp(Q/temperature);
        the closer temperature is to 0 the more rational the agent is.
    epochs : int
        Number of iterations gradient descent will run.
    learning_rate : float
        Learning rate for gradient descent.
    theta : 1D numpy array
        Initial reward function parameters vector with the length equal to the 
        #features.
    Returns
    -------
    1D numpy array
        Reward function parameters computed with Maximum Causal Entropy 
        algorithm from the expert trajectories.
    '''    
    
    # Compute the state-action visitation counts and the probability 
    # of a trajectory starting in state s from the expert trajectories.
    sa_visit_count, P_0 = compute_s_a_visitations(mdp, gamma, trajectories)
    
    # Mean state visitation count of expert trajectories
    # mean_s_visit_count[s] = ( \sum_{i,t} 1_{traj_s_{i,t} = s}) / num_traj
    mean_s_visit_count = np.sum(sa_visit_count,1) / trajectories.shape[0]
    # Mean feature count of expert trajectories
    mean_f_count = np.dot(feature_matrix.T, mean_s_visit_count)
    
    if theta is None:
        theta = np.random.rand(feature_matrix.shape[1])
        

    for i in range(epochs):
        r = np.squeeze(np.asarray(np.dot(feature_matrix, theta.reshape(-1,1))))
        # Compute the Boltzmann rational policy \pi_{s,a} = \exp(Q_{s,a} - V_s) 
        V, Q, policy = vi_boltzmann(mdp, gamma, r, h, temperature)
        
        # IRL log likelihood term: 
        # L = 0; for all traj: for all (s, a) in traj: L += Q[s,a] - V[s]
        L = np.sum(sa_visit_count * (Q - V))
        
        # The expected #times policy π visits state s in a given #timesteps.
        D = compute_D(mdp, gamma, policy, P_0, t_max=trajectories.shape[1])        

        # IRL log likelihood gradient w.r.t rewardparameters. 
        # Corresponds to line 9 of Algorithm 2 from the MaxCausalEnt IRL paper 
        # www.cs.cmu.edu/~bziebart/publications/maximum-causal-entropy.pdf. 
        # Negate to get the gradient of neg log likelihood, 
        # which is then minimized with GD.
        dL_dtheta = -(mean_f_count - np.dot(feature_matrix.T, D))

        # Gradient descent
        theta = theta - learning_rate * dL_dtheta
        theta[theta<0] = 0
        theta[theta>1] = 1

        if (i+1)%10==0: 
            print('Epoch: {} log likelihood of all traj: {}'.format(i,L), 
                  ', average per traj step: {}'.format(
                  L/(trajectories.shape[0] * trajectories.shape[1])))
    return theta, policy