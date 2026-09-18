"use client";

import {
  type InfiniteData,
  type QueryKey,
  type UseInfiniteQueryOptions,
  type UseQueryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
} from "@tanstack/react-query";
import { useSession } from "@/lib/auth";
import {
  type BackendRequestError,
  type BackendRequestOptions,
  requestBackend,
} from "./request";

export function useBackendIdentity(fallbackIdentity?: string) {
  const { data: session } = useSession();
  return session?.user?.id ?? fallbackIdentity ?? "anonymous";
}

export const backendQueryKeys = {
  chatHistory: (identity: string) =>
    ["backend", "user", identity, "chat-history"] as const,
  chatMessages: (identity: string, chatId: string) =>
    ["backend", "user", identity, "chat-messages", chatId] as const,
  members: (identity: string) =>
    ["backend", "user", identity, "members"] as const,
  accessCandidates: (identity: string) =>
    ["backend", "user", identity, "access-candidates"] as const,
  invitations: (identity: string) =>
    ["backend", "user", identity, "invitations"] as const,
  models: (identity: string) =>
    ["backend", "user", identity, "models"] as const,
  knowledgeBases: (identity: string) =>
    ["backend", "user", identity, "knowledge-bases"] as const,
};

type BackendQueryOptions<TData> = {
  init?: RequestInit;
  path: RequestInfo | URL;
  queryKey: QueryKey;
  requestOptions?: BackendRequestOptions;
} & Omit<
  UseQueryOptions<TData, BackendRequestError, TData, QueryKey>,
  "queryFn" | "queryKey"
>;

export function useBackendQuery<TData>({
  init,
  path,
  queryKey,
  requestOptions,
  ...options
}: BackendQueryOptions<TData>) {
  return useQuery<TData, BackendRequestError, TData, QueryKey>({
    ...options,
    queryFn: ({ signal }) =>
      requestBackend<TData>(path, {
        ...init,
        signal,
      }, requestOptions),
    queryKey,
  });
}

type BackendInfiniteQueryOptions<TData, TPageParam> = {
  init?: RequestInit;
  initialPageParam: TPageParam;
  path: (pageParam: TPageParam) => RequestInfo | URL;
  queryKey: QueryKey;
} & Omit<
  UseInfiniteQueryOptions<
    TData,
    BackendRequestError,
    InfiniteData<TData, TPageParam>,
    QueryKey,
    TPageParam
  >,
  "initialPageParam" | "queryFn" | "queryKey"
>;

export function useBackendInfiniteQuery<TData, TPageParam>({
  init,
  path,
  queryKey,
  ...options
}: BackendInfiniteQueryOptions<TData, TPageParam>) {
  return useInfiniteQuery<
    TData,
    BackendRequestError,
    InfiniteData<TData, TPageParam>,
    QueryKey,
    TPageParam
  >({
    ...options,
    queryFn: ({ pageParam, signal }) =>
      requestBackend<TData>(path(pageParam as TPageParam), {
        ...init,
        signal,
      }),
    queryKey,
  });
}

type BackendMutationOptions<TVariables> = {
  mutationKey?: QueryKey;
  request: (variables: TVariables) => {
    init?: RequestInit;
    path: RequestInfo | URL;
  };
};

export function useBackendMutation<TData = unknown, TVariables = void>({
  mutationKey,
  request,
}: BackendMutationOptions<TVariables>) {
  return useMutation<TData, BackendRequestError, TVariables>({
    mutationFn: (variables) => {
      const target = request(variables);
      return requestBackend<TData>(target.path, target.init);
    },
    mutationKey,
  });
}
