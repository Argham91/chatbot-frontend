// Robust number formatting to prevent crashes
export const safeNumber = (v?: number | string | null, decimals: number = 2): string => {
  if (v === undefined || v === null || v === '') return "—";
  const num = typeof v === 'string' ? parseFloat(v) : v;
  if (isNaN(num)) return "—";
  
  // If it's an integer, don't show decimals unless forced (optional behavior, sticking to toLocaleString for now)
  return num.toLocaleString(undefined, { 
    minimumFractionDigits: 0, 
    maximumFractionDigits: decimals 
  });
};

export const safeDecimal = (v?: number | string | null, decimals: number = 2): string => {
  if (v === undefined || v === null || v === '') return "—";
  const num = typeof v === 'string' ? parseFloat(v) : v;
  if (isNaN(num)) return "—";
  return num.toFixed(decimals);
};
