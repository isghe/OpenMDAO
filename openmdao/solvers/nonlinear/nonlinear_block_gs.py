"""Define the NonlinearBlockGS class."""

from openmdao.solvers.solver import NonlinearSolver


class NonlinearBlockGS(NonlinearSolver):
    """
    Nonlinear block Gauss-Seidel solver.
    """

    SOLVER = 'NL: NLBGS'

    def _setup_solvers(self, system, depth):
        """
        Assign system instance, set depth, and optionally perform setup.

        Parameters
        ----------
        system : <System>
            pointer to the owning system.
        depth : int
            depth of the current system (already incremented).
        """
        super(NonlinearBlockGS, self)._setup_solvers(system, depth)

        if len(system._subsystems_allprocs) != len(system._subsystems_myproc):
            raise RuntimeError('Nonlinear Gauss-Seidel cannot be used on a parallel group.')

    def _declare_options(self):
        """
        Declare options before kwargs are processed in the init method.
        """
        
        self.options.declare('use_aitken', type_=bool, default=False,
                             desc='set to True to use Aitken relaxation')
        self.options.declare('aitken_min_factor', default=0.1,
                             desc='lower limit for Aitken relaxation factor')
        self.options.declare('aitken_max_factor', default=1.5,
                             desc='upper limit for Aitken relaxation factor')

    def _iter_initialize(self):
        """
        Perform any necessary pre-processing operations.

        Returns
        -------
        float
            initial error.
        float
            error at the first iteration.
        """
        self._aitken_work1 = self._outputs._clone()
        self._aitken_work2 = self._outputs._clone()
        self._aitken_work3 = self._outputs._clone()
        self._aitken_work4 = self._outputs._clone()
        self._theta_n_1 = 1.
        
        return super(NonlinearBlockGS, self)._iter_initialize()        
    
    def _iter_execute(self):
        """
        Perform the operations in the iteration loop.
        """
        system = self._system
        outputs = self._outputs
        
        use_aitken = self.options(['use_aitken'])
        aitken_min_factor = self.options(['aitken_min_factor'])
        aitken_max_factor = self.options(['aitken_max_factor'])
        
        delta_outputs_n_1 = self._aitken_work1
        delta_outputs_n = self._aitken_work2
        outputs_n = self._aitken_work3
        work = self._aitken_work4
        theta_n_1 = self._theta_n_1
        
        delta_outputs_n.set_vec(outputs) # cache the outputs, replaced by change in outputs later 
        outputs_n.set_vec(outputs) # cache the outputs

        self._solver_info.prefix += '|  '
        for isub, subsys in enumerate(system._subsystems_myproc):
            system._transfer('nonlinear', 'fwd', isub)
            subsys._solve_nonlinear()
            system._check_reconf_update()

        delta_outputs_n -= outputs # compute change in the outputs after the NLBGS iteration
        delta_outputs_n *= -1 # compute change in the outputs after the NLBGS iteration

        if self._iter_count >= 1 and use_aitken:
            # Compute relaxation factor
            # This method is used by Kenway et al. in "Scalable Parallel  
            # Approach for High-Fidelity Steady-State Aeroelastic Analysis 
            # and Adjoint Derivative Computations" (line 22 of Algorithm 1)
            work.set_vec(delta_outputs_n)
            work -= delta_outputs_n_1
            numerator = work.dot(delta_outputs_n)
            denominator = work.get_norm() ** 2
            theta_n = theta_n_1 * ( 1 - numerator / denominator )
            theta_n = max(aitken_min_factor, min(aitken_max_factor, theta_n)) # limit relaxation factor to the specified range
            theta_n_1 = theta_n # save relaxation factor for the next iteration
        else:
            theta_n = 1.

        outputs.set_vec(outputs_n)
        outputs.add_scal_vec(theta_n, delta_outputs_n)

        delta_outputs_n_1.set_vec(delta_outputs_n) # save update to use in next iteration             

        self._solver_info.prefix = self._solver_info.prefix[:-3]

    def _mpi_print_header(self):
        """
        Print header text before solving.
        """
        if (self.options['iprint'] > 0 and self._system.comm.rank == 0):

            pathname = self._system.pathname
            if pathname:
                nchar = len(pathname)
                prefix = self._solver_info.prefix
                header = prefix + "\n"
                header += prefix + nchar * "=" + "\n"
                header += prefix + pathname + "\n"
                header += prefix + nchar * "="
                print(header)
