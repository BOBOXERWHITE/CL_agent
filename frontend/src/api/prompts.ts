import { postJson, requestJson } from "./client";

export interface PromptTemplate {
  id: string;
  name: string;
  task_type: string;
  template: string;
  version: number;
  status: string;
  created_at: string;
  updated_at: string;
}

interface PromptTemplateListResponse {
  items: PromptTemplate[];
}

interface CreatePromptTemplateInput {
  name: string;
  taskType: string;
  template: string;
}

export async function listPromptTemplates(): Promise<PromptTemplate[]> {
  const response = await requestJson<PromptTemplateListResponse>("/api/prompts");
  return response.items;
}

export async function createPromptTemplate(
  input: CreatePromptTemplateInput,
): Promise<PromptTemplate> {
  return postJson<PromptTemplate>("/api/prompts", {
    name: input.name,
    task_type: input.taskType,
    template: input.template,
  });
}

export async function activatePromptTemplate(promptTemplateId: string): Promise<PromptTemplate> {
  return postJson<PromptTemplate>(`/api/prompts/${promptTemplateId}/activate`, {});
}
