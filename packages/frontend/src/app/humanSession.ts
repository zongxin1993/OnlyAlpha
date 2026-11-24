import { z } from "zod";

export const humanSessionPath = "/api/v2/human/session";
export const humanSessionSchema = z.strictObject({
    subject_id: z.string().min(1),
    can_logout: z.boolean()
});
export type HumanSession = z.infer<typeof humanSessionSchema>;

let storageSubject: string | null = null;

export function bindHumanSession(session: HumanSession) {
    storageSubject = session.can_logout ? session.subject_id : null;
}

export function humanStorageKey(key: string): string {
    return storageSubject === null ? key : JSON.stringify(["onlyalpha.human", storageSubject, key]);
}

export const humanSessionStorage = {
    getItem: (key: string) => sessionStorage.getItem(humanStorageKey(key)),
    setItem: (key: string, value: string) => {
        sessionStorage.setItem(humanStorageKey(key), value);
    },
    removeItem: (key: string) => {
        sessionStorage.removeItem(humanStorageKey(key));
    }
};

export function sessionRequest(method: "GET" | "POST" | "DELETE", credential?: string) {
    return fetch(humanSessionPath, {
        method,
        mode: "same-origin",
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: credential === undefined ? {} : { Authorization: `Bearer ${credential}` }
    });
}
