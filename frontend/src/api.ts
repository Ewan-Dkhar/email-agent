/**
 * Type-Safe API Client for FastAPI Backend.
 * Uses proxied /api routes to avoid CORS overhead.
 */

import {
  AgentLoopResult,
  DraftRecord,
  HealthResponse,
  PriorityTier,
  SyncResult,
  TaskDetailOut,
  TaskOut,
  TaskStatus,
} from './types';

const BASE_URL = '/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Request failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE_URL}/health`);
  return handleResponse<HealthResponse>(res);
}

export async function getTasks(
  statusFilter?: TaskStatus,
  priorityFilter?: PriorityTier
): Promise<TaskOut[]> {
  const params = new URLSearchParams();
  if (statusFilter) params.append('status', statusFilter);
  if (priorityFilter) params.append('priority', priorityFilter);

  const url = `${BASE_URL}/tasks${params.toString() ? `?${params.toString()}` : ''}`;
  const res = await fetch(url);
  return handleResponse<TaskOut[]>(res);
}

export async function getTaskDetail(taskId: number): Promise<TaskDetailOut> {
  const res = await fetch(`${BASE_URL}/tasks/${taskId}`);
  return handleResponse<TaskDetailOut>(res);
}

export async function updateTaskStatus(
  taskId: number,
  status: TaskStatus
): Promise<TaskOut> {
  const res = await fetch(`${BASE_URL}/tasks/${taskId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  return handleResponse<TaskOut>(res);
}

export async function runTaskCopilot(
  taskId: number,
  instruction: string
): Promise<AgentLoopResult> {
  const res = await fetch(`${BASE_URL}/tasks/${taskId}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction }),
  });
  return handleResponse<AgentLoopResult>(res);
}

export async function syncEmails(): Promise<SyncResult> {
  const res = await fetch(`${BASE_URL}/sync`, {
    method: 'POST',
  });
  return handleResponse<SyncResult>(res);
}

export async function getDraft(draftId: string): Promise<DraftRecord> {
  const res = await fetch(`${BASE_URL}/drafts/${draftId}`);
  return handleResponse<DraftRecord>(res);
}

export async function approveDraft(draftId: string): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE_URL}/drafts/${draftId}/approve`, {
    method: 'POST',
  });
  return handleResponse<{ status: string; message: string }>(res);
}
