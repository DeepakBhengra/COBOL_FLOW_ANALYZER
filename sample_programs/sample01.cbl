       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDPROC.
      * Sample order-processing program used to exercise the flow analyzer.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO 'ORDERS.DAT'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EOF        PIC X VALUE 'N'.
       01 WS-AMOUNT     PIC 9(7)V99 VALUE 0.
       01 WS-ERR-CODE   PIC 99 VALUE 0.
       01 WS-COUNT      PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM INIT-PARA.
           PERFORM READ-INPUT UNTIL WS-EOF = 'Y'.
           PERFORM CLEANUP-PARA.
           STOP RUN.
       INIT-PARA.
           MOVE 'N' TO WS-EOF.
           MOVE 0 TO WS-COUNT.
       READ-INPUT.
           READ ORDER-FILE
               AT END MOVE 'Y' TO WS-EOF
               NOT AT END PERFORM PROCESS-RECORD
           END-READ.
       PROCESS-RECORD.
           ADD 1 TO WS-COUNT.
           IF WS-AMOUNT > 0
               PERFORM VALIDATE-AMOUNT THRU VALIDATE-EXIT
           ELSE
               PERFORM ERROR-PARA
           END-IF.
           EVALUATE WS-ERR-CODE
               WHEN 0
                   PERFORM WRITE-OUTPUT
               WHEN 99
                   GO TO ABORT-PARA
               WHEN OTHER
                   PERFORM ERROR-PARA
           END-EVALUATE.
       VALIDATE-AMOUNT.
           IF WS-AMOUNT > 100000
               MOVE 5 TO WS-ERR-CODE
               PERFORM ERROR-PARA
               GO TO VALIDATE-EXIT
           END-IF.
           CALL 'AMTCHK' USING WS-AMOUNT WS-ERR-CODE.
       VALIDATE-EXIT.
           EXIT.
       WRITE-OUTPUT.
           WRITE OUT-REC FROM WS-AMOUNT
               INVALID KEY PERFORM ERROR-PARA
           END-WRITE.
       ERROR-PARA.
           DISPLAY 'ERROR CODE ' WS-ERR-CODE.
           MOVE 'Y' TO WS-EOF.
       ABORT-PARA.
           DISPLAY 'ABORT'.
           STOP RUN.
       CLEANUP-PARA.
           CLOSE ORDER-FILE.
       UNUSED-PARA.
           DISPLAY 'NEVER RUN'.
