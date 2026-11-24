import {
    createContext,
    useContext,
    useEffect,
    useRef,
    useState,
    type SubmitEvent,
    type ReactNode
} from "react";
import {
    bindHumanSession,
    humanSessionSchema,
    sessionRequest,
    type HumanSession
} from "./humanSession";
import "./humanSession.css";

const SessionContext = createContext<{ subject: string; logout: () => void } | null>(null);

export function HumanSessionControls() {
    const session = useContext(SessionContext);
    return (
        session && (
            <div className="human-session-controls">
                <span title={session.subject}>当前用户：{session.subject}</span>
                <button type="button" onClick={session.logout}>
                    退出登录
                </button>
            </div>
        )
    );
}

type State =
    | { kind: "checking" | "login" | "unavailable"; message?: string }
    | { kind: "active"; session: HumanSession };

async function currentSession(): Promise<State> {
    const response = await sessionRequest("GET");
    if (response.status === 401) return { kind: "login" };
    if (response.status !== 200) throw new Error();
    return { kind: "active", session: humanSessionSchema.parse(await response.json()) };
}

export function HumanSessionGate({ children }: { children: ReactNode }) {
    const [state, setState] = useState<State>({ kind: "checking" });
    const [busy, setBusy] = useState(false);
    const input = useRef<HTMLInputElement>(null);
    const initial = useRef<Promise<State> | null>(null);
    const channel = useRef<BroadcastChannel | null>(null);

    useEffect(() => {
        let active = true;
        const changes = new BroadcastChannel("onlyalpha.human.session");
        channel.current = changes;
        changes.onmessage = () => {
            window.location.reload();
        };
        const onRestore = (event: PageTransitionEvent) => {
            if (event.persisted) window.location.reload();
        };
        window.addEventListener("pageshow", onRestore);
        initial.current ??= currentSession();
        void initial.current
            .then((next) => {
                if (!active) return;
                if (next.kind === "active") bindHumanSession(next.session);
                setState(next);
            })
            .catch(() => {
                if (active)
                    setState({
                        kind: "unavailable",
                        message: "无法确认登录状态，请检查工作台服务后重试。"
                    });
            });
        return () => {
            active = false;
            changes.close();
            window.removeEventListener("pageshow", onRestore);
        };
    }, []);

    const refreshSessions = () => {
        channel.current?.postMessage("changed");
        window.location.reload();
    };
    const login = async (event: SubmitEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !input.current) return;
        setBusy(true);
        const request = sessionRequest("POST", input.current.value);
        input.current.value = "";
        try {
            const response = await request;
            if (response.status === 401) {
                setState({ kind: "login", message: "登录凭据无效，请核对后重新输入。" });
                return;
            }
            if (
                response.status !== 200 ||
                !humanSessionSchema.parse(await response.json()).can_logout
            )
                throw new Error();
            refreshSessions();
        } catch {
            setState({
                kind: "unavailable",
                message: "暂时无法确认登录结果，请重新查看登录状态。"
            });
        } finally {
            setBusy(false);
        }
    };
    const logout = async () => {
        setState({ kind: "checking", message: "正在退出登录…" });
        try {
            const response = await sessionRequest("DELETE");
            if (response.status !== 204 && response.status !== 401) throw new Error();
            refreshSessions();
        } catch {
            setState({
                kind: "unavailable",
                message: "暂时无法确认退出结果，请重新查看登录状态。"
            });
        }
    };
    if (state.kind === "active") {
        const session = state.session;
        return (
            <SessionContext
                value={
                    session.can_logout
                        ? { subject: session.subject_id, logout: () => void logout() }
                        : null
                }
            >
                {children}
            </SessionContext>
        );
    }
    return (
        <main className="human-session-page">
            {state.kind === "login" ? (
                <form
                    className="human-session-card"
                    onSubmit={(event) => void login(event)}
                    autoComplete="off"
                >
                    <h1>登录 OnlyAlpha 工作台</h1>
                    <label htmlFor="human-credential">登录凭据</label>
                    <input
                        id="human-credential"
                        ref={input}
                        type="password"
                        autoComplete="off"
                        spellCheck={false}
                        required
                        pattern="[0-9A-Fa-f]{64}"
                        title="请输入部署方提供的 64 位十六进制凭据"
                        aria-describedby="credential-help"
                    />
                    <p id="credential-help">请输入部署方为你分配的 64 位凭据。</p>
                    {state.message && <p role="alert">{state.message}</p>}
                    <button type="submit" disabled={busy}>
                        {busy ? "正在登录…" : "登录"}
                    </button>
                </form>
            ) : (
                <section className="human-session-card">
                    <p role={state.kind === "checking" ? "status" : "alert"}>
                        {state.message ?? "正在确认登录状态…"}
                    </p>
                    {state.kind === "unavailable" && (
                        <button
                            type="button"
                            onClick={() => {
                                window.location.reload();
                            }}
                        >
                            重新查看登录状态
                        </button>
                    )}
                </section>
            )}
        </main>
    );
}
