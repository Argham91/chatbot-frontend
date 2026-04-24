import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { DateRange, DateContextType, DatePreset } from '../types';

const DateContext = createContext<DateContextType | undefined>(undefined);

export const useDateRange = () => {
  const context = useContext(DateContext);
  if (!context) {
    throw new Error('useDateRange must be used within a DateRangeProvider');
  }
  return context;
};

// Helper to get formatted date string YYYY-MM-DD
const toDate = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

export const DateRangeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [dateRange, setDateRangeState] = useState<DateRange>(() => {
    // Default: This Month (1st to Yesterday)
    const today = new Date();
    let start = new Date(today.getFullYear(), today.getMonth(), 1);
    const end = new Date(today);
    end.setDate(today.getDate() - 1); // Yesterday

    // Edge case: If today is the 1st, yesterday falls in the previous month
    // so start (1st of current month) > end (last day of prev month) → invalid range.
    // Fall back to previous month so data is always visible.
    if (end < start) {
      start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    }

    return {
      startDate: start,
      endDate: end,
      preset: 'thisMonth',
    };
  });

  const setPreset = useCallback((preset: DatePreset) => {
    const today = new Date();
    let start = new Date();
    let end = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    switch (preset) {
      case 'thisMonth':
        start = new Date(today.getFullYear(), today.getMonth(), 1);
        end = yesterday;
        // If today is the 1st, start > end → fall back to previous month
        if (end < start) {
          start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        }
        break;
      case 'thisWeek':
        // T-7 to T-1
        end = yesterday;
        start = new Date(yesterday);
        start.setDate(yesterday.getDate() - 6);
        break;
      case 'prevMonth':
        start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        end = new Date(today.getFullYear(), today.getMonth(), 0);
        break;
      case 'prevFinancialYear': {
        // Previous FY: April 1 of last FY → March 31 of last FY
        // Indian FY runs April 1 → March 31
        // If current month is Apr–Dec (index 3–11) → prev FY started last calendar year
        // If current month is Jan–Mar (index 0–2)  → prev FY started 2 calendar years ago
        const prevFyStartYear = today.getMonth() >= 3 ? today.getFullYear() - 1 : today.getFullYear() - 2;
        start = new Date(prevFyStartYear, 3, 1);      // April 1 of previous FY
        end   = new Date(prevFyStartYear + 1, 2, 31); // March 31 of previous FY
        break;
      }
      case 'currentFinancialYear': {
        // Current FY: April 1 of current FY → yesterday (to date)
        const curFyStartYear = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
        start = new Date(curFyStartYear, 3, 1); // April 1 of current FY
        end   = yesterday;
        // If today is April 1 (first day of FY), fall back to previous FY to avoid empty range
        if (end < start) {
          start = new Date(curFyStartYear - 1, 3, 1);
          end   = new Date(curFyStartYear, 2, 31);
        }
        break;
      }
      case 'custom':
        // No change to dates, just mode switch, or keep current
        return;
    }

    setDateRangeState({ startDate: start, endDate: end, preset });
  }, []);

  const setDateRange = (range: DateRange) => {
    setDateRangeState(range);
  };

  return (
    <DateContext.Provider value={{ dateRange, setDateRange, setPreset }}>
      {children}
    </DateContext.Provider>
  );
};
