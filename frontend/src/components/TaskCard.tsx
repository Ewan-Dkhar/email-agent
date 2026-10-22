import React from 'react';
import { TaskOut, TaskStatus } from '../types';
import { PriorityBadge } from './PriorityBadge';
import { ExternalLink, Bot, CheckCircle2, Clock } from 'lucide-react';

interface TaskCardProps {
  task: TaskOut;
  onSelectTask: (task: TaskOut) => void;
  onStatusChange: (taskId: number, newStatus: TaskStatus) => void;
}

export const TaskCard: React.FC<TaskCardProps> = ({
  task,
  onSelectTask,
  onStatusChange,
}) => {
  const isCompleted = task.status === 'COMPLETED';
  const isDismissed = task.status === 'DISMISSED';

  const isDeadlinePassed = task.deadline
    ? new Date(task.deadline.replace(' ', 'T')).getTime() < Date.now()
    : false;

  const toggleComplete = (e: React.MouseEvent) => {
    e.stopPropagation();
    const nextStatus: TaskStatus = isCompleted ? 'PENDING' : 'COMPLETED';
    onStatusChange(task.id, nextStatus);
  };

  return (
    <div
      style={{
        backgroundColor: '#ffffff',
        border: '1px solid #e5e7eb',
        borderRadius: '8px',
        padding: '16px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        opacity: isCompleted || isDismissed ? 0.65 : 1,
        transition: 'all 0.15s ease-in-out',
      }}
    >
      {/* Top Header: Priority, Title & Deadline */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <PriorityBadge priority={task.priority_tier} />
            <span style={{ fontSize: '12px', color: '#6b7280' }}>
              #{task.id}
            </span>
          </div>
          <h3
            style={{
              margin: '4px 0 0 0',
              fontSize: '16px',
              fontWeight: '600',
              color: '#111827',
              textDecoration: isCompleted ? 'line-through' : 'none',
            }}
          >
            {task.title}
          </h3>
        </div>

        {task.deadline && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '12px',
              fontWeight: '500',
              color: isDeadlinePassed
                ? '#6b7280'
                : task.priority_tier === 'P1_CRITICAL'
                ? '#b91c1c'
                : '#1d4ed8',
              backgroundColor: isDeadlinePassed
                ? '#f3f4f6'
                : task.priority_tier === 'P1_CRITICAL'
                ? '#fef2f2'
                : '#eff6ff',
              padding: '4px 8px',
              borderRadius: '6px',
              whiteSpace: 'nowrap',
              textDecoration: isDeadlinePassed ? 'line-through' : 'none',
            }}
          >
            <Clock size={14} />
            <span>{task.deadline} {isDeadlinePassed ? '(Passed)' : ''}</span>
          </div>
        )}
      </div>

      {/* Summary */}
      <p style={{ margin: 0, fontSize: '14px', color: '#374151', lineHeight: '1.45' }}>
        {task.summary}
      </p>

      {/* Email Context Line */}
      <div
        style={{
          fontSize: '12px',
          color: '#6b7280',
          backgroundColor: '#f9fafb',
          padding: '6px 10px',
          borderRadius: '4px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '8px',
          flexWrap: 'wrap',
        }}
      >
        <span style={{ maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          <strong>From:</strong> {task.sender}
        </span>
        <span style={{ maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          <strong>Subject:</strong> {task.subject}
        </span>
        {task.received_at && (
          <span style={{ fontSize: '11px', color: '#6b7280', marginLeft: 'auto', whiteSpace: 'nowrap' }}>
            📅 {task.received_at}
          </span>
        )}
      </div>

      {/* Card Actions Footer */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: '4px',
          paddingTop: '8px',
          borderTop: '1px solid #f3f4f6',
        }}
      >
        <div style={{ display: 'flex', gap: '8px' }}>
          {task.action_url && (
            <a
              href={task.action_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                fontSize: '13px',
                color: '#2563eb',
                textDecoration: 'none',
                fontWeight: '500',
              }}
            >
              <ExternalLink size={14} />
              Open Link
            </a>
          )}
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={toggleComplete}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '6px 12px',
              fontSize: '13px',
              fontWeight: '500',
              borderRadius: '6px',
              border: '1px solid #d1d5db',
              backgroundColor: isCompleted ? '#dcfce7' : '#ffffff',
              color: isCompleted ? '#15803d' : '#374151',
              cursor: 'pointer',
            }}
          >
            <CheckCircle2 size={14} />
            {isCompleted ? 'Completed' : 'Mark Done'}
          </button>

          <button
            onClick={() => onSelectTask(task)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              fontSize: '13px',
              fontWeight: '600',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: '#1f2937',
              color: '#ffffff',
              cursor: 'pointer',
            }}
          >
            <Bot size={14} />
            Work with Co-Pilot
          </button>
        </div>
      </div>
    </div>
  );
};
