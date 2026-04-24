import React from 'react';
import {
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { ChatBlock } from '../../types';

// Colour palette shared across all chatbot charts
const CHART_COLORS = ['#3b82f6', '#f97316', '#22c55e', '#a855f7', '#ef4444', '#06b6d4', '#eab308'];

// ---------------------------------------------------------------------------
// Sub-renderers
// ---------------------------------------------------------------------------

const TextBlock: React.FC<{ content: string }> = ({ content }) => (
  <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">{content}</p>
);

const TableBlock: React.FC<{ headers: string[]; rows: (string | number)[][] }> = ({ headers, rows }) => (
  <div className="overflow-x-auto mt-1 rounded-lg border border-gray-200">
    <table className="min-w-full text-xs">
      <thead className="bg-blue-600 text-white">
        <tr>
          {headers.map((h, i) => (
            <th key={i} className="px-3 py-2 text-left font-semibold whitespace-nowrap">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, ri) => (
          <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
            {row.map((cell, ci) => (
              <td key={ci} className="px-3 py-2 text-gray-700 whitespace-nowrap border-b border-gray-100">
                {String(cell ?? '--')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const BarChartBlock: React.FC<{ block: ChatBlock }> = ({ block }) => {
  const { data = [], series = [], x_key = 'name', title } = block;
  return (
    <div className="mt-2">
      {title && <p className="text-xs font-semibold text-gray-600 mb-1">{title}</p>}
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey={x_key} tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} width={45} />
          <Tooltip contentStyle={{ fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map((s, i) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={s.color || CHART_COLORS[i % CHART_COLORS.length]}
              radius={[3, 3, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

const LineChartBlock: React.FC<{ block: ChatBlock }> = ({ block }) => {
  const { data = [], series = [], x_key = 'date', title } = block;
  return (
    <div className="mt-2">
      {title && <p className="text-xs font-semibold text-gray-600 mb-1">{title}</p>}
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey={x_key} tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} width={45} />
          <Tooltip contentStyle={{ fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map((s, i) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color || CHART_COLORS[i % CHART_COLORS.length]}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

const PieChartBlock: React.FC<{ block: ChatBlock }> = ({ block }) => {
  const { data = [], x_key = 'name', title } = block;
  // For pie charts, "series[0].key" holds the value field name (default "value")
  const valueKey = block.series?.[0]?.key || 'value';

  return (
    <div className="mt-2">
      {title && <p className="text-xs font-semibold text-gray-600 mb-1">{title}</p>}
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={data}
            dataKey={valueKey}
            nameKey={x_key}
            cx="50%"
            cy="50%"
            outerRadius={75}
            label={({ name, percent }) => `${name} ${(percent * 100).toFixed(1)}%`}
            labelLine={false}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={{ fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main renderer — dispatches to sub-renderers by block type
// ---------------------------------------------------------------------------

interface Props {
  blocks: ChatBlock[];
}

const ResponseRenderer: React.FC<Props> = ({ blocks }) => (
  <div className="space-y-2">
    {blocks.map((block, i) => {
      switch (block.type) {
        case 'text':
          return <TextBlock key={i} content={block.content || ''} />;

        case 'table':
          return block.headers && block.rows ? (
            <TableBlock key={i} headers={block.headers} rows={block.rows} />
          ) : null;

        case 'chart':
          if (!block.data || block.data.length === 0) return null;
          if (block.chart_type === 'pie')  return <PieChartBlock  key={i} block={block} />;
          if (block.chart_type === 'line') return <LineChartBlock key={i} block={block} />;
          return <BarChartBlock key={i} block={block} />;  // default to bar

        default:
          return null;
      }
    })}
  </div>
);

export default ResponseRenderer;
