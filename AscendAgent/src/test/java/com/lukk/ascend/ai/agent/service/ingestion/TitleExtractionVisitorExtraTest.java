package com.lukk.ascend.ai.agent.service.ingestion;

import org.commonmark.node.Heading;
import org.commonmark.node.SoftLineBreak;
import org.commonmark.node.Text;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Extra branch coverage for TitleExtractionVisitor:
 *  - H2/H3 headings are ignored
 *  - H1 with non-Text first child is ignored
 *  - Title is set only once (second H1 does not override)
 */
class TitleExtractionVisitorExtraTest {

    @Test
    @DisplayName("visit ignores H2 headings")
    void visit_H2Heading_TitleRemainsNull() {
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();
        Heading h2 = new Heading();
        h2.setLevel(2);
        h2.appendChild(new Text("Subtitle"));

        visitor.visit(h2);

        assertThat(visitor.getTitle()).isNull();
    }

    @Test
    @DisplayName("visit ignores H1 heading when first child is not a Text node")
    void visit_H1WithNonTextFirstChild_TitleRemainsNull() {
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();
        Heading h1 = new Heading();
        h1.setLevel(1);
        // SoftLineBreak is a Node but not a Text node
        h1.appendChild(new SoftLineBreak());

        visitor.visit(h1);

        assertThat(visitor.getTitle()).isNull();
    }

    @Test
    @DisplayName("visit captures only the first H1 heading when multiple H1s are present")
    void visit_MultipleH1s_OnlyFirstCaptured() {
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();

        Heading first = new Heading();
        first.setLevel(1);
        first.appendChild(new Text("First Title"));

        Heading second = new Heading();
        second.setLevel(1);
        second.appendChild(new Text("Second Title"));

        visitor.visit(first);
        visitor.visit(second);

        assertThat(visitor.getTitle()).isEqualTo("First Title");
    }
}
