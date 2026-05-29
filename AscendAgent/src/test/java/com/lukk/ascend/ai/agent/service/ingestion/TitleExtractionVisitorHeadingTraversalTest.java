package com.lukk.ascend.ai.agent.service.ingestion;

import org.commonmark.node.Heading;
import org.commonmark.node.SoftLineBreak;
import org.commonmark.node.Text;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class TitleExtractionVisitorHeadingTraversalTest {

    @Test
    @DisplayName("visit ignores H2 headings")
    void visit_H2Heading_TitleRemainsNull() {
        // given
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();
        Heading h2 = new Heading();
        h2.setLevel(2);
        h2.appendChild(new Text("Subtitle"));

        // when
        visitor.visit(h2);

        // then
        assertThat(visitor.getTitle()).isNull();
    }

    @Test
    @DisplayName("visit ignores H1 heading when first child is not a Text node")
    void visit_H1WithNonTextFirstChild_TitleRemainsNull() {
        // given
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();
        Heading h1 = new Heading();
        h1.setLevel(1);
        // SoftLineBreak is a Node but not a Text node
        h1.appendChild(new SoftLineBreak());

        // when
        visitor.visit(h1);

        // then
        assertThat(visitor.getTitle()).isNull();
    }

    @Test
    @DisplayName("visit captures only the first H1 heading when multiple H1s are present")
    void visit_MultipleH1s_OnlyFirstCaptured() {
        // given
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();
        Heading first = new Heading();
        first.setLevel(1);
        first.appendChild(new Text("First Title"));
        Heading second = new Heading();
        second.setLevel(1);
        second.appendChild(new Text("Second Title"));

        // when
        visitor.visit(first);
        visitor.visit(second);

        // then
        assertThat(visitor.getTitle()).isEqualTo("First Title");
    }
}
