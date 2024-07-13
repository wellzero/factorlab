import pandas as pd
from typing import Optional, Union, Any, List
import os

from factorlab.strategy_backtesting.portfolio_optimization.naive import NaiveOptimization
from factorlab.strategy_backtesting.portfolio_optimization.mvo import MVO
from factorlab.strategy_backtesting.portfolio_optimization.clustering import HRP, HERC
from factorlab.data_viz.plot import plot_bar

from joblib import Parallel, delayed


class PortfolioOptimization:
    """
    Portfolio optimization class.

    This class computes the optimized portfolio weights or returns based on the signals of the assets or strategies.
    """

    def __init__(self,
                 returns: Union[pd.DataFrame, pd.Series],
                 method: str = 'equal_weight',
                 lags: int = 1,
                 risk_free_rate: Optional[float] = 0.0,
                 as_excess_returns: bool = False,
                 max_weight: float = 1.0,
                 min_weight: float = 0.0,
                 leverage: float = 1.0,
                 risk_aversion: float = 1.0,
                 exp_ret_method: Optional[str] = 'mean',
                 cov_matrix_method: Optional[str] = 'covariance',
                 target_return: Optional[float] = 0.15,
                 target_risk: Optional[float] = 0.1,
                 risk_measure: str = 'variance',
                 alpha: float = 0.05,
                 t_cost: Optional[float] = None,
                 rebal_freq: Optional[Union[str, int]] = None,
                 window_type: str = 'rolling',
                 window_size: Optional[int] = None,
                 parallelize: bool = False,
                 n_jobs: Optional[int] = None,
                 asset_names: Optional[List[str]] = None,
                 ann_factor: Optional[int] = None,
                 side_weights: Optional[pd.Series] = None,
                 solver: Optional[str] = None,
                 **kwargs: Any
                 ):
        """
        Constructor

        Parameters
        ----------
        returns : pd.DataFrame or pd.Series
            Returns of the assets or strategies.
        method: str, {'equal_weight', 'inverse_variance', 'inverse_vol', 'target_vol', 'random',
         'min_vol', 'max_return_min_vol', 'max_sharpe', 'max_diversification', 'efficient_return', 'efficient_risk',
          'risk_parity', 'hrp', 'herc'}, default 'equal_weight'
            Optimization method to compute weights.
        lags: int, default 1
            Number of periods to lag weights.
        risk_free_rate: float, default 0.0
            Risk-free rate.
        as_excess_returns: bool, default False
            Whether to compute excess returns.
        max_weight: float, default 1.0
            Maximum weight of the assets or strategies.
        min_weight: float, default 0.0
            Minimum weight of the assets or strategies.
        leverage: float, default 1.0
            Leverage factor.
        risk_aversion: float, default 1.0
            Risk aversion factor.
        exp_ret_method: str, default 'mean'
            Method to compute the expected returns.
        cov_matrix_method: str, default 'covariance'
            Method to compute the covariance matrix.
        target_return: float, default 0.15
            Target return for the optimization.
        target_risk: float, default 0.1
            Target risk for the optimization.
        risk_measure: str, default 'variance'
            Risk measure for the optimization.
        alpha: float, default 0.05
            Significance level for the risk measure.
        t_cost: float, default None
            Transaction costs.
        rebal_freq: str, int, default None
            Rebalancing frequency.
        window_type: str, default 'rolling'
            Window type for the optimization.
        window_size: int, default None
            Window size for the optimization.
        parallelize: bool, default False
            Whether to parallelize the computation.
        n_jobs: int, default None
            Number of jobs to run in parallel.
        asset_names: list, default None
            Names of the assets or strategies.
        ann_factor: int, default None
            Annualization factor.
        side_weights: pd.Series, default None
            Side weights for the hierarchical optimization.
        solver: str, default None
            Solver for the optimization.
        kwargs: dict
            Additional keyword arguments.
        """
        self.returns = returns
        self.method = method
        self.lags = lags
        self.risk_free_rate = risk_free_rate
        self.as_excess_returns = as_excess_returns
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.leverage = leverage
        self.risk_aversion = risk_aversion
        self.exp_ret_method = exp_ret_method
        self.cov_matrix_method = cov_matrix_method
        self.target_return = target_return
        self.target_risk = target_risk
        self.risk_measure = risk_measure
        self.alpha = alpha
        self.t_cost = t_cost
        self.rebal_freq = rebal_freq
        self.window_type = window_type
        self.window_size = window_size
        self.parallelize = parallelize
        self.n_jobs = n_jobs
        self.asset_names = asset_names
        self.ann_factor = ann_factor
        self.side_weights = side_weights
        self.solver = solver
        self.kwargs = kwargs
        self.freq = None
        self.signal_returns = None
        self.weights = None
        self.optimizer = None
        self.weighted_signals = None
        self.t_costs = None
        self.portfolio_ret = None
        self.preprocess_data()

    def preprocess_data(self) -> None:
        """
        Preprocesses data.
        """
        # returns
        if not isinstance(self.returns, pd.DataFrame) and not isinstance(self.returns, pd.Series):  # check data type
            raise ValueError('returns must be a pd.DataFrame or pd.Series')
        if isinstance(self.returns, pd.Series):  # convert to df
            self.returns = self.returns.to_frame()
        if isinstance(self.returns.index, pd.MultiIndex):  # convert to single index
            self.returns = self.returns.unstack()

        # method
        if self.method not in ['equal_weight', 'inverse_variance', 'inverse_vol', 'target_vol', 'random',
                               'min_vol', 'max_return_min_vol', 'max_sharpe', 'max_diversification',
                               'efficient_return', 'efficient_risk', 'risk_parity', 'hrp', 'herc']:
            raise ValueError("Method is not supported. Valid methods are: 'equal_weight', 'inverse_variance',"
                             "'inverse_vol', 'target_vol', 'random', 'min_vol', 'max_return_min_vol', "
                             "'max_sharpe', 'max_diversification', 'efficient_return', 'efficient_risk', "
                             "'risk_parity', 'hrp', 'herc'")

        # ann_factor
        if self.ann_factor is None:
            self.ann_factor = self.returns.groupby(self.returns.index.year).count().max().mode()[0]

        # freq
        self.freq = pd.infer_freq(self.returns.index)
        if self.freq is None:
            if self.ann_factor == 1:
                self.freq = 'Y'
            elif self.ann_factor == 4:
                self.freq = 'Q'
            elif self.ann_factor == 12:
                self.freq = 'M'
            elif self.ann_factor == 52:
                self.freq = 'W'
            else:
                self.freq = 'D'

        # window_size
        if self.window_size is None:
            self.window_size = self.ann_factor

        # n jobs
        if self.parallelize and self.n_jobs is None:
            self.n_jobs = os.cpu_count()

    def get_optimizer(self, returns: pd.DataFrame) -> Any:
        """
        Optimization algorithm.
        """
        # naive optimization
        if self.method in ['equal_weight', 'inverse_variance', 'inverse_vol', 'target_vol', 'random']:
            self.optimizer = NaiveOptimization(returns, method=self.method, leverage=self.leverage,
                                               target_vol=self.target_risk, **self.kwargs)

        # mean variance optimization
        elif self.method in ['min_vol', 'max_return_min_vol', 'max_sharpe', 'max_diversification', 'efficient_return',
                             'efficient_risk', 'risk_parity']:
            self.optimizer = MVO(returns, method=self.method, max_weight=self.max_weight, min_weight=self.min_weight,
                                 budget=self.leverage, risk_aversion=self.risk_aversion,
                                 risk_free_rate=self.risk_free_rate, as_excess_returns=self.as_excess_returns,
                                 exp_ret_method=self.exp_ret_method, cov_matrix_method=self.cov_matrix_method,
                                 target_return=self.target_return, target_risk=self.target_risk, solver=self.solver,
                                 ann_factor=self.ann_factor, **self.kwargs)

        # hierarchical risk parity
        elif self.method == 'hrp':
            self.optimizer = HRP(returns, cov_matrix_method=self.cov_matrix_method, side_weights=self.side_weights,
                                 leverage=self.leverage, **self.kwargs)

        # hierarchical equal risk contributions
        elif self.method == 'herc':
            self.optimizer = HERC(returns, risk_measure=self.risk_measure, alpha=self.alpha,
                                  cov_matrix_method=self.cov_matrix_method, leverage=self.leverage, **self.kwargs)

        else:
            raise ValueError("Method is not supported. Valid methods are: 'equal_weight', 'inverse_variance',"
                             "'inverse_vol', 'target_vol', 'random', 'min_vol', 'max_return_min_vol', "
                             "'max_sharpe', 'max_diversification', 'efficient_return', 'efficient_risk', 'risk_parity',"
                             " 'hrp', 'herc'")

        return self.optimizer

    def compute_fixed_weights(self) -> pd.DataFrame:
        """
        Compute optimal weights.
        """
        # initialize optimization
        self.get_optimizer(self.returns)

        # compute weights
        self.weights = self.optimizer.compute_weights()

        return self.weights.astype(float)

    def compute_expanding_window_weights(self) -> pd.DataFrame:
        """
        Compute expanding window weights.

        Returns
        -------
        exp_weights: pd.DataFrame
            Expanding weights.
        """
        # dates
        dates = self.returns.dropna().index[self.window_size - 1:]

        def compute_weights_for_date(end_date):
            data_window = self.returns.loc[:end_date]
            self.get_optimizer(data_window)
            w = self.optimizer.compute_weights()
            return end_date, w.values.flatten()

        results = Parallel(n_jobs=self.n_jobs)(delayed(compute_weights_for_date)(date) for date in dates)

        self.weights = pd.DataFrame(index=dates, columns=self.returns.columns)
        for date, weights in results:
            self.weights.loc[date] = weights

        return self.weights.astype(float)

    def compute_rolling_window_weights(self) -> pd.DataFrame:
        """
        Compute rolling window weights.

        Returns
        -------
        rolling_weights: pd.DataFrame
            Rolling weights.
        """
        # dates
        dates = self.returns.dropna().index[self.window_size - 1:]

        def compute_weights_for_date(end_date):
            start_date = end_date - pd.DateOffset(days=self.window_size - 1)
            data_window = self.returns.loc[start_date:end_date]
            self.get_optimizer(data_window)
            w = self.optimizer.compute_weights()
            return end_date, w.values.flatten()

        results = Parallel(n_jobs=self.n_jobs)(delayed(compute_weights_for_date)(date) for date in dates)

        self.weights = pd.DataFrame(index=dates, columns=self.returns.columns)
        for date, weights in results:
            self.weights.loc[date] = weights

        return self.weights.astype(float)

    def get_weights(self) -> pd.DataFrame:
        """
        Compute optimal weights.
        """
        if self.window_type == 'expanding':
            self.weights = self.compute_expanding_window_weights()
        elif self.window_type == 'rolling':
            self.weights = self.compute_rolling_window_weights()
        else:
            self.compute_fixed_weights()

        # lag weights
        self.weights = self.weights.shift(self.lags)

        return self.weights

    def rebalance_portfolio(self) -> pd.DataFrame:
        """
        Rebalance portfolio weights.

        Returns
        -------
        signals: pd.DataFrame
            Rebalanced portfolio weights with DatetimeIndex and weights (cols).
        """
        # frequency dictionary
        freq_dict = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5,
                     'sunday': 6, '15th': 15, 'month_end': 'is_month_end', 'month_start': 'is_month_start'}

        # rebalancing
        if self.rebal_freq is not None:

            w = self.weights.copy()

            # day of the week
            if self.rebal_freq in list(freq_dict.keys())[:7]:
                rebal_df = w[w.index.dayofweek == freq_dict[self.rebal_freq]]
            # mid-month
            elif self.rebal_freq == '15th':
                rebal_df = w[w.index.day == 15]
            # fixed period
            elif isinstance(self.rebal_freq, int):
                rebal_df = w.iloc[::self.rebal_freq, :]
            # month start, month end
            else:
                rebal_df = w[getattr(w.index, freq_dict[self.rebal_freq])]

            # reindex and forward fill
            self.weights = rebal_df.reindex(w.index).ffill().dropna(how='all')

        return self.weights

    def compute_tcosts(self) -> pd.DataFrame:
        """
        Computes transactions costs from changes in weights.

        Returns
        -------
        t_costs: pd.Series
            Series with DatetimeIndex (level 0), tickers (level 1) and transaction costs (cols).
        """
        # no t-costs
        if self.t_cost is None:
            self.t_costs = pd.DataFrame(data=0, index=self.weights.index, columns=self.weights.columns)
        # t-costs
        else:
            self.t_costs = self.weights.diff().abs() * self.t_cost

        return self.t_costs

    def compute_portfolio_returns(self) -> pd.DataFrame:
        """
        Computes optimized portfolio returns.
        """
        # get weights
        self.get_weights()

        # rebalance portfolio
        self.rebalance_portfolio()

        # t-costs
        self.compute_tcosts()

        # compute gross returns
        self.portfolio_ret = self.weights.mul(self.returns.reindex(self.weights.index), axis=0)

        # compute net returns
        self.portfolio_ret = self.portfolio_ret.subtract(self.t_costs, axis=0).dropna(how='all')

        # compute portfolio returns
        self.portfolio_ret = self.portfolio_ret.sum(axis=1)

        return self.portfolio_ret

    def plot_weights(self):
        """
        Plot the optimized portfolio weights.
        """
        # plot h bar
        plot_bar(self.weights.T.sort_values(by=[self.returns.index[-1]]), axis='horizontal', x_label='weights')
