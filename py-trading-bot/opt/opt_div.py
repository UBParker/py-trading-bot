from core import presel

import vectorbtpro as vbt
from vectorbtpro.utils.config import Config
import numpy as np

from opt.opt_main import OptMain

#Script to optimize the underlying combination of patterns/signals used for a given preselection strategy
#Divergence use only exit signal from the underlying strategies, no need to variate the entry strategy

#The optimization takes place on the actions from CAC40, DAX and Nasdaq
#Parameters very good on some actions but very bad for others should not be selected

#The optimization algorithm calculates one point, look for the points around it and select the best one
#As it can obviously lead to local maximum, the starting point is selected in a random manner

vbt.settings['caching']=Config(
    disable=True,
    disable_whitelist=True,
    disable_machinery=True,
    silence_warnings=False,
    register_lazily=True,
    ignore_args=[
        'jitted',
        'chunked'
    ],
    use_cached_accessors=True
)

class Opt(OptMain):
    def __init__(self,period,**kwargs):
        super().__init__(period,**kwargs)
        self.bti={}
        
        for ind in self.indexes:
            self.bti[ind]=presel.Presel(ind,period)

    def calculate_eq_ret(self,pf):
        m_rb=pf.total_market_return
        m_rr=pf.get_total_return()
        
        if abs(m_rb)<0.1: #avoid division by zero
            p=(m_rr)/ 0.1*np.sign(m_rb)   
        else:
            p=(m_rr- m_rb )/ abs(m_rb)

        return 4*p*(p<0) + p*(p>0) #wrong direction for the return are penalyzed

    def calculate_pf(self, best_arrs_cand, best_ret_cand, best_arrs_ret,key):
        if not self.check_tested_arrs():
            return best_arrs_cand, best_ret_cand

        #create the underlying strategy
        self.defi_ex(key)
            
        ret=0
        ret_arr=[]

        for ind in self.indexes: #CAC, DAX, NASDAQ
            self.bti[ind].overwrite_ex_strat_underlying(self.exs[ind])
            self.bti[ind].preselect_divergence()

            pf=vbt.Portfolio.from_signals(self.bti[ind].close, 
                                          self.bti[ind].entries,
                                          self.bti[ind].exits,
                                          #short_entries=self.bti[ind].entries_short,
                                          #short_exits=self.bti[ind].exits_short,
                                          freq="1d",fees=self.fees,
                                          call_seq='auto',cash_sharing=True,)
            
            ret_arr.append(self.calculate_eq_ret(pf))

        ret=self.summarize_eq_ret(ret_arr)
        trades =len(pf.get_trades().records_arr)
        del pf
        
        if ret> best_arrs_ret and ret>best_ret_cand and trades>50:
            return self.calc_arrs, ret
        
        return best_arrs_cand, best_ret_cand
        


     