import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import {
    FetchWatchlistApiClient,
    WatchlistWebError,
    type Watchlist,
    type WatchlistBook,
    type WatchlistMember,
    type WatchlistSave
} from "../../api/watchlists/client";
import { createUuidV4 } from "../../api/integrations/submissionIntent";

const PENDING = "onlyalpha.watchlist.pending-command";
export const watchlistMemberKey = (member: WatchlistMember): string =>
    JSON.stringify([
        member.source.integration_id,
        member.source.integration_revision_fingerprint,
        member.source.expected_type_id,
        member.instrument_id
    ]);
function retainedCommand(): string | null {
    try {
        return sessionStorage.getItem(PENDING);
    } catch {
        return null;
    }
}
const messageFor = (error: unknown): string => {
    if (!(error instanceof WatchlistWebError) || !error.definitive)
        return "提交结果尚未确认，请核对提交结果；不会重复提交。";
    if (error.code === "WATCHLIST_VERSION_CONFLICT")
        return "其他窗口已修改自选，请重新加载后再编辑。";
    if (error.code === "WATCHLIST_INVALID")
        return "无法保存：请检查名称是否重复，或自选数量是否已达上限。";
    if (error.code === "WATCHLIST_OWNER_REQUIRED" || /FORBIDDEN|UNAUTHORIZED/.test(error.code))
        return "当前无权修改自选，请检查登录或权限。";
    return "自选未保存，请重新加载后重试。";
};

/** One server configuration projection shared by the search dialog and sidebar. */
export function useWatchlists(credentials: LocalReadCredentials) {
    const api = useMemo(() => new FetchWatchlistApiClient(credentials), [credentials]);
    const [book, setBook] = useState<WatchlistBook | null>(null);
    const [selected, setSelected] = useState("");
    const [pending, setPending] = useState<string | null>(retainedCommand);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const writing = useRef(false);
    const generation = useRef(0);
    const invalidate = useCallback(() => {
        generation.current++;
    }, []);
    const active = book?.lists.find((list) => list.list_id === selected) ?? book?.lists[0];
    const reload = useCallback(async () => {
        if (writing.current) return;
        const current = ++generation.current;
        try {
            const value = await api.read();
            if (current === generation.current) {
                setBook(value);
                setMessage(null);
            }
        } catch {
            if (current === generation.current) setMessage("自选暂不可用，请重新加载。");
        }
    }, [api]);
    useEffect(() => {
        const controller = new AbortController();
        const current = ++generation.current;
        void api
            .read(controller.signal)
            .then((value) => {
                if (!controller.signal.aborted && current === generation.current) setBook(value);
            })
            .catch(() => {
                if (!controller.signal.aborted && current === generation.current)
                    setMessage("自选暂不可用，请重新加载。");
            });
        return () => {
            controller.abort();
            invalidate();
        };
    }, [api, invalidate]);
    const clearPending = (command: string) => {
        if (sessionStorage.getItem(PENDING) === command) sessionStorage.removeItem(PENDING);
        setPending((current) => (current === command ? null : current));
    };
    const save = async (lists: readonly Watchlist[]) => {
        if (book === null || writing.current || pending !== null) return false;
        writing.current = true;
        setBusy(true);
        ++generation.current;
        const intent: WatchlistSave = {
            schema_version: 2,
            command_id: createUuidV4(),
            expected_version: book.version,
            lists
        };
        try {
            sessionStorage.setItem(PENDING, intent.command_id);
        } catch {
            setMessage("无法保留提交标识，本次未提交；请检查站点会话存储权限。");
            writing.current = false;
            setBusy(false);
            return false;
        }
        setPending(intent.command_id);
        setMessage(null);
        try {
            const saved = await api.save(intent);
            setBook(saved);
            clearPending(intent.command_id);
            setMessage("已保存");
            return true;
        } catch (error) {
            setMessage(messageFor(error));
            if (error instanceof WatchlistWebError && error.definitive) {
                try {
                    clearPending(intent.command_id);
                } catch {
                    /* Retain queryable command if storage becomes unavailable. */
                }
            }
            return false;
        } finally {
            writing.current = false;
            setBusy(false);
        }
    };
    const toggle = async (member: WatchlistMember) => {
        if (book === null) return false;
        const key = watchlistMemberKey(member);
        if (active === undefined)
            return save([{ list_id: createUuidV4(), name: "自选", members: [member] }]);
        const present = active.members.some((item) => watchlistMemberKey(item) === key);
        return save(
            book.lists.map((list) =>
                list.list_id === active.list_id
                    ? {
                          ...list,
                          members: present
                              ? list.members.filter((item) => watchlistMemberKey(item) !== key)
                              : [...list.members, member]
                      }
                    : list
            )
        );
    };
    const resolvePending = async () => {
        if (pending === null || writing.current) return;
        writing.current = true;
        setBusy(true);
        ++generation.current;
        try {
            await api.command(pending);
            const latest = await api.read();
            setBook(latest);
            clearPending(pending);
            setMessage("提交结果已确认，已刷新自选。");
        } catch {
            setMessage("提交结果仍未确认，请稍后再次核对。");
        } finally {
            writing.current = false;
            setBusy(false);
        }
    };
    return {
        book,
        active,
        selected,
        setSelected,
        busy,
        pending,
        message,
        reload,
        save,
        toggle,
        resolvePending
    };
}
export type WatchlistController = ReturnType<typeof useWatchlists>;
