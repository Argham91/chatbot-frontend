// Robustly transforms various object shapes into chart-ready arrays
export const objectToChartArray = (
  obj: any, 
  keyLabel: string = "name", 
  valueKey: string = "value"
): any[] => {
  if (!obj || typeof obj !== 'object') return [];
  
  return Object.entries(obj).map(([key, val]) => {
    let numericValue = 0;
    
    // Handle { "High": 100 }
    if (typeof val === 'number') {
      numericValue = val;
    } 
    // Handle { "High": { "qty_Mt": 100 } } or similar nested structures
    else if (typeof val === 'object' && val !== null) {
      // safe cast to any to check common property names
      const v = val as any;
      numericValue = v.qty_Mt ?? v.qty ?? v.value ?? v.amount ?? 0;
    }

    return {
      [keyLabel]: key,
      [valueKey]: numericValue
    };
  });
};

export const safeNumber = (val: any): number => {
  if (typeof val === 'number') return val;
  if (typeof val === 'string') {
    const parsed = parseFloat(val);
    return isNaN(parsed) ? 0 : parsed;
  }
  return 0;
};
