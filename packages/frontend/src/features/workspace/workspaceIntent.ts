import type { WorkspaceStudy } from "../../api/workspace/client";
import { studyDescriptor, type ChartStudyInstance } from "./chartStudy";
/** Only the user-editable intent crosses persistence; no capability or numeric result. */
export function workspaceStudyIntent(instance: ChartStudyInstance): WorkspaceStudy {
    const descriptor = studyDescriptor(instance.selection),
        presentation = instance.presentation;
    return {
        kind: descriptor.kind,
        type_id: descriptor.typeId,
        semantic_version: descriptor.semanticVersion,
        parameters: { ...instance.configuration.parameters },
        output_names: [...instance.configuration.outputNames],
        presentation: {
            placement: presentation.placement,
            color: presentation.color,
            line_width: presentation.lineWidth,
            opacity: presentation.opacity,
            visible: presentation.visible,
            series_styles: { ...presentation.seriesStyles }
        }
    };
}
