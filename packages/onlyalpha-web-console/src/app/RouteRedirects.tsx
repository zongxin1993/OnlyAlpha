import { Navigate, useParams } from "react-router-dom";

export function CompatibilityResultRedirect() {
    const { researchResultFingerprint = "" } = useParams();
    return <Navigate to={`/research/results/${researchResultFingerprint}`} replace />;
}

export function CompatibilityStatisticsRedirect() {
    const { researchResultFingerprint = "", statisticsFingerprint = "" } = useParams();
    return (
        <Navigate
            to={`/research/results/${researchResultFingerprint}/statistics/${statisticsFingerprint}`}
            replace
        />
    );
}
