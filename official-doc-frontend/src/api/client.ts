import type { ApiResponse } from '../types/document';

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  setBaseUrl(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  endpoint(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  resolveUrl(pathOrUrl: string): string {
    if (/^https?:\/\//i.test(pathOrUrl)) {
      return pathOrUrl;
    }

    if (pathOrUrl.startsWith('/')) {
      if (/^https?:\/\//i.test(this.baseUrl)) {
        return new URL(pathOrUrl, this.baseUrl).toString();
      }

      return pathOrUrl;
    }

    return this.endpoint(`/${pathOrUrl}`);
  }

  async json<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(this.endpoint(path), options);
    const text = await response.text();
    const result = parseJson<ApiResponse<T>>(text);

    if (!response.ok) {
      throw new Error(result?.message || `HTTP ${response.status}`);
    }

    if (result && result.code !== 0) {
      throw new Error(result.message || '接口返回失败');
    }

    return result?.data as T;
  }

  async rawJson<T>(path: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    const response = await fetch(this.endpoint(path), options);
    const text = await response.text();
    const result = parseJson<ApiResponse<T>>(text);

    if (!response.ok) {
      throw new Error(result?.message || `HTTP ${response.status}`);
    }

    if (!result) {
      throw new Error('接口未返回合法 JSON');
    }

    if (result.code !== 0) {
      throw new Error(result.message || '接口返回失败');
    }

    return result;
  }
}

function parseJson<T>(text: string): T | null {
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}
