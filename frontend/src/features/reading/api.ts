import { paperApi, paperEndpoints } from "@/features/paper/api";

/**
 * The reading paper's client, and how short it is is the point.
 *
 * Everything a reading paper needs is either shared with listening or one
 * path segment different from it, so there is nothing to write here but the
 * binding. What listening has and this does not is the transcript behind a
 * recording — the one thing a paper that is read has no counterpart for.
 */
export const readingApi = {
  ...paperApi,
  ...paperEndpoints("reading"),
};
