package com.lukk.ascend.ai.orchestrator.service.ingestion;

import lombok.Getter;
import org.commonmark.node.AbstractVisitor;
import org.commonmark.node.Heading;
import org.commonmark.node.Node;
import org.commonmark.node.Text;

@Getter
public class TitleExtractionVisitor extends AbstractVisitor {
    private static final int H1_LEVEL = 1;
    private String title;

    @Override
    public void visit(Heading heading) {
        if (heading.getLevel() == H1_LEVEL && title == null) {
            Node child = heading.getFirstChild();
            if (child instanceof Text textNode) {
                title = textNode.getLiteral();
            }
        }
    }

}
